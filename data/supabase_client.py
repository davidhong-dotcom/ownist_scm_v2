"""
data/supabase_client.py
-----------------------
Supabase DB 연결 및 출고 데이터 upsert, 조회 관련 기능

[shipping_data 테이블 스키마]
  create table public.shipping_data (
    id              uuid default gen_random_uuid() primary key,
    shipping_date   date not null,
    order_company   text default '',
    order_number    text default '',
    product_code    text not null,
    product_name    text default '',
    quantity        numeric not null default 0,
    order_amount    numeric default 0,
    created_at      timestamp with time zone default timezone('utc', now()) not null,
    unique (shipping_date, order_number, product_code)
  );
"""

import streamlit as st
import pandas as pd
from supabase import create_client, Client
import datetime


# ────────────────────────────────────────────────
# 클라이언트 초기화 (싱글톤)
# ────────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except KeyError:
        st.error("Supabase 설정 오류: `.streamlit/secrets.toml`에 [supabase] url / key를 설정해주세요.")
        st.stop()
    except Exception as e:
        st.error(f"Supabase 클라이언트 생성 오류: {e}")
        st.stop()


# ────────────────────────────────────────────────
# 기간별 출고완료 내역 upsert
# 입력 DataFrame 컬럼:
#   출고일자, 주문사, 주문번호, 상품코드, 상품명, 출고량, 주문금액합계
# ────────────────────────────────────────────────
def upsert_ownist_shipping(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """
    기간별 출고완료 내역을 Supabase shipping_data 테이블에 upsert.
    (shipping_date, order_number, product_code) 조합이 unique key.
    단, 이미 DB에 존재하는 주문번호(order_number)의 경우 업로드(df)에서 제외합니다.
    업로드 건수와 중복이 제거된 데이터프레임을 반환합니다.
    """
    supabase = get_supabase()
    
    # 1. 업로드하려는 주문번호 중 이미 존재하는 주문번호 조회
    existing_order_numbers = set()
    if "주문번호" in df.columns:
        # 빈 값 제거 후 중복 제거된 리스트 생성
        # 단, "집계-" 로 시작하는 가짜 주문번호는 중복 체크에서 제외 (upsert로 날짜별 덮어쓰기 처리)
        order_numbers_to_check = df["주문번호"].dropna().astype(str).str.strip()
        order_numbers_to_check = order_numbers_to_check[~order_numbers_to_check.str.startswith("집계-")].unique().tolist()
        order_numbers_to_check = [on for on in order_numbers_to_check if on]
        
        if order_numbers_to_check:
            # in_ 필터 한도 초과를 막기 위해 500건씩 나누어 조회
            chunk_size = 500
            for i in range(0, len(order_numbers_to_check), chunk_size):
                chunk = order_numbers_to_check[i : i + chunk_size]
                response = supabase.table("shipping_data").select("order_number").in_("order_number", chunk).execute()
                if response.data:
                    existing_order_numbers.update([row["order_number"] for row in response.data])
                    
    # 2. DataFrame에서 중복 주문번호 행 제거 (DB에 존재하는 주문건 제외)
    if existing_order_numbers:
        df = df[~df["주문번호"].astype(str).str.strip().isin(existing_order_numbers)].copy()
        
    # 3. 엑셀 파일 내부의 동일 출고일자, 주문번호, 상품코드 중복행 합산 처리 (삭제 방지)
    df = df.groupby(
        ["출고일자", "주문사", "주문번호", "상품코드", "상품명"], 
        as_index=False, dropna=False
    ).agg({
        "출고량": "sum",
        "주문금액합계": "max" # 주문금액합계는 이미 주문번호 기준으로 전체 합산되어 있으므로 max 유지
    })

    records = []

    for _, row in df.iterrows():
        d = row["출고일자"]
        date_str = d.strftime("%Y-%m-%d") if isinstance(d, datetime.date) else str(d)

        records.append({
            "shipping_date": date_str,
            "order_company": str(row.get("주문사", "")).strip(),
            "order_number":  str(row.get("주문번호", "")).strip(),
            "product_code":  str(row["상품코드"]).strip(),
            "product_name":  str(row.get("상품명", "")).strip(),
            "quantity":      float(row["출고량"]),
            "order_amount":  float(row.get("주문금액합계", 0)),
        })

    if not records:
        return 0, df

    # 1000건씩 나눠서 upsert
    batch_size = 1000
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        supabase.table("shipping_data").upsert(
            batch, 
            on_conflict="shipping_date,order_number,product_code"
        ).execute()

    return len(records), df


# ────────────────────────────────────────────────
# 기존 호환용 upsert (WMS 엑셀 형식, 상품코드+출고일자만)
# ────────────────────────────────────────────────
def upsert_shipping_data(df: pd.DataFrame) -> int:
    """
    기존 WMS 형식(출고일자, 상품코드, 출고수량)을 Supabase에 upsert.
    """
    supabase = get_supabase()
    records = []

    for _, row in df.iterrows():
        d = row["출고일자"]
        date_str = d.strftime("%Y-%m-%d") if isinstance(d, datetime.date) else str(d)
        records.append({
            "shipping_date": date_str,
            "order_company": "",
            "order_number":  "",
            "product_code":  str(row["상품코드"]).strip(),
            "product_name":  "",
            "quantity":      float(row["출고수량"]),
            "order_amount":  0.0,
        })

    batch_size = 1000
    for i in range(0, len(records), batch_size):
        supabase.table("shipping_data").upsert(
            records[i : i + batch_size],
            on_conflict="shipping_date,order_number,product_code"
        ).execute()

    return len(records)


# ────────────────────────────────────────────────
# 출고 데이터 조회
# ────────────────────────────────────────────────
def fetch_shipping_data(start_date=None, end_date=None) -> pd.DataFrame:
    """
    Supabase에서 출고 데이터 조회.
    반환 DataFrame 컬럼:
        출고일자, 주문사, 주문번호, 상품코드, 상품명, 출고수량, 주문금액합계
    """
    supabase = get_supabase()

    query = supabase.table("shipping_data").select("*")
    if start_date:
        query = query.gte("shipping_date", str(start_date))
    if end_date:
        query = query.lte("shipping_date", str(end_date))

    all_data = []
    page_size = 1000
    start_idx = 0

    while True:
        response = query.range(start_idx, start_idx + page_size - 1).execute()
        data = response.data
        if not data:
            break
        all_data.extend(data)
        if len(data) < page_size:
            break
        start_idx += page_size

    if not all_data:
        return pd.DataFrame(columns=[
            "출고일자", "주문사", "주문번호",
            "상품코드", "상품명", "출고수량", "주문금액합계"
        ])

    df = pd.DataFrame(all_data)
    df = df.rename(columns={
        "shipping_date": "출고일자",
        "order_company": "주문사",
        "order_number":  "주문번호",
        "product_code":  "상품코드",
        "product_name":  "상품명",
        "quantity":      "출고수량",
        "order_amount":  "주문금액합계",
    })

    df["출고일자"]     = pd.to_datetime(df["출고일자"]).dt.date
    df["출고수량"]     = df["출고수량"].astype(float)
    df["주문금액합계"] = df["주문금액합계"].fillna(0).astype(float)

    keep = ["출고일자", "주문사", "주문번호", "상품코드", "상품명", "출고수량", "주문금액합계"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


# ────────────────────────────────────────────────
# 현재고 데이터 upsert 및 fetch
# ────────────────────────────────────────────────
def upsert_inventory_data(df: pd.DataFrame) -> int:
    """
    현재고 데이터를 Supabase inventory_data 테이블에 upsert (product_code 기준).
    df: parse_inventory_file() 결과를 받음 (컬럼: 상품코드, 현재고)
    
    주의: 현재고의 특성상 새 파일을 올릴 때 기존 재고를 모두 삭제(초기화)한 뒤 새 데이터를 넣습니다.
    """
    supabase = get_supabase()
    
    # 1. 기존 데이터 전체 초기화 (삭제)
    # PostgREST에서는 필터 없이 delete가 불가능하므로 neq 필터 활용
    supabase.table("inventory_data").delete().neq("product_code", "DUMMY_DELETE_ALL").execute()
    
    # 2. 새 데이터 생성
    records = []
    for _, row in df.iterrows():
        records.append({
            "product_code": str(row["상품코드"]).strip(),
            "stock_quantity": float(row["현재고"]),
            "updated_at": datetime.datetime.utcnow().isoformat()
        })

    if not records:
        return 0

    batch_size = 1000
    for i in range(0, len(records), batch_size):
        supabase.table("inventory_data").upsert(
            records[i : i + batch_size],
            on_conflict="product_code"
        ).execute()

    return len(records)


def fetch_inventory_data() -> pd.DataFrame:
    """
    Supabase에서 최신 현재고 데이터 조회
    반환 DataFrame 컬럼: 상품코드, 현재고
    """
    supabase = get_supabase()

    response = supabase.table("inventory_data").select("product_code, stock_quantity").limit(100000).execute()
    data = response.data

    if not data:
        return None

    df = pd.DataFrame(data)
    df = df.rename(columns={
        "product_code": "상품코드",
        "stock_quantity": "현재고"
    })
    
    df["현재고"] = df["현재고"].astype(float)
    return df
