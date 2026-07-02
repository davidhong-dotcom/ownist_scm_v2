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
def upsert_ownist_shipping(df: pd.DataFrame, channel: str = "CK로지스", is_cumulative: bool = False) -> tuple[int, pd.DataFrame]:
    """
    기간별 출고완료 내역을 Supabase shipping_data 테이블에 upsert.
    is_cumulative=True일 경우:
      - df에 포함된 출고량이 특정 기간의 '누적'임을 의미함.
      - 대상 월(Month)의 1일부터 대상 일자(Target Date) 전일까지 DB에 저장된 기존 출고량 총합을 구한 뒤,
        현재 df의 출고량에서 빼서 순수 해당 일자의 출고량(Delta)만 저장함.
    """
    supabase = get_supabase()
    
    # 1. 업로드하려는 주문번호 중 이미 존재하는 주문번호 조회
    # (단, is_cumulative=True인 누적 데이터는 항상 덮어쓰기 하므로 중복 체크를 생략합니다.)
    existing_order_numbers = set()
    if "주문번호" in df.columns and not is_cumulative:
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

    # 4. 누적 데이터 역산 (Delta 로직)
    if is_cumulative and not df.empty:
        # 업로드된 기준 일자 (모든 행이 같은 날짜라고 가정)
        target_date = df["출고일자"].iloc[0]
        if isinstance(target_date, str):
            target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
            
        if "조회시작일" in df.columns:
            first_day = df["조회시작일"].iloc[0]
            if isinstance(first_day, str):
                first_day = datetime.datetime.strptime(first_day, "%Y-%m-%d").date()
        else:
            first_day = target_date.replace(day=1)
            
        # 당월 1일(혹은 지정한 시작일)부터 오늘(target_date)까지의 기존 데이터 가져오기
        # 주의: target_date 당일에 이미 입력된 데이터는 '누적' 계산에서 제외해야 중복 차감이 안됨
        resp = supabase.table("shipping_data") \
            .select("product_code, quantity, shipping_date") \
            .eq("channel", channel) \
            .gte("shipping_date", first_day.strftime("%Y-%m-%d")) \
            .execute()
            
        existing_monthly_data = pd.DataFrame(resp.data) if resp.data else pd.DataFrame(columns=["product_code", "quantity", "shipping_date"])
        
        # 오늘(target_date) 데이터 제외
        if not existing_monthly_data.empty:
            existing_monthly_data = existing_monthly_data[existing_monthly_data["shipping_date"] != target_date.strftime("%Y-%m-%d")]
            # 상품코드별 합계
            monthly_sum = existing_monthly_data.groupby("product_code")["quantity"].sum().to_dict()
        else:
            monthly_sum = {}
            
        # Delta 계산
        df["출고량"] = df.apply(
            lambda r: r["출고량"] - monthly_sum.get(str(r["상품코드"]).strip(), 0), 
            axis=1
        )

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
            "channel":       channel,
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
def upsert_shipping_data(df: pd.DataFrame, channel: str = "CK로지스") -> int:
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
            "channel":       channel,
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
        "channel":       "채널",
    })

    df["출고일자"]     = pd.to_datetime(df["출고일자"]).dt.date
    df["출고수량"]     = df["출고수량"].astype(float)
    df["주문금액합계"] = df["주문금액합계"].fillna(0).astype(float)
    if "채널" not in df.columns:
        df["채널"] = "CK로지스"

    keep = ["출고일자", "주문사", "주문번호", "상품코드", "상품명", "출고수량", "주문금액합계", "채널"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


# ────────────────────────────────────────────────
# 현재고 데이터 upsert 및 fetch
# ────────────────────────────────────────────────
def upsert_inventory_data(df: pd.DataFrame, channel: str = "CK로지스") -> int:
    """
    현재고 데이터를 Supabase inventory_data 테이블에 upsert (product_code 기준).
    df: parse_inventory_file() 결과를 받음 (컬럼: 상품코드, 현재고)
    
    주의: 현재고의 특성상 새 파일을 올릴 때 기존 재고를 모두 삭제(초기화)한 뒤 새 데이터를 넣습니다.
    (수정됨: 전체 삭제 대신 지정된 channel의 데이터만 삭제)
    """
    supabase = get_supabase()
    
    # 1. 해당 채널의 데이터만 초기화 (삭제)
    supabase.table("inventory_data").delete().eq("channel", channel).execute()
    
    # 2. 동일 상품코드끼리 현재고 합산 (원시 데이터 내 중복 방지)
    df_agg = df.groupby("상품코드", as_index=False)["현재고"].sum()

    records = []
    for _, row in df_agg.iterrows():
        # 채널명을 상품코드 뒤에 붙여 고유 키 생성 (Supabase PK 중복 방지)
        unique_code = f"{str(row['상품코드']).strip()}_{channel}"
        records.append({
            "product_code": unique_code,
            "stock_quantity": float(row["현재고"]),
            "updated_at": datetime.datetime.utcnow().isoformat(),
            "channel": channel,
        })

    if not records:
        return 0

    batch_size = 1000
    for i in range(0, len(records), batch_size):
        # 삭제 후 insert 하므로 upsert 대신 insert 사용 (on_conflict 불필요)
        supabase.table("inventory_data").insert(
            records[i : i + batch_size]
        ).execute()

    return len(records)


def fetch_inventory_data() -> pd.DataFrame:
    """
    Supabase에서 최신 현재고 데이터 조회
    반환 DataFrame 컬럼: 상품코드, 현재고, 채널
    """
    supabase = get_supabase()

    response = supabase.table("inventory_data").select("product_code, stock_quantity, channel").limit(100000).execute()
    data = response.data

    if not data:
        return None

    df = pd.DataFrame(data)
    
    # 생성된 고유 키에서 채널명 접미사 제거하여 원래 상품코드로 복원
    def clean_code(row):
        code = str(row['product_code'])
        ch = str(row.get('channel', ''))
        suffix = f"_{ch}"
        if ch and code.endswith(suffix):
            return code[:-len(suffix)]
        return code
        
    df['product_code'] = df.apply(clean_code, axis=1)

    df = df.rename(columns={
        "product_code": "상품코드",
        "stock_quantity": "현재고",
        "channel": "채널"
    })
    
    if "채널" not in df.columns:
        df["채널"] = "CK로지스"
    
    df["현재고"] = df["현재고"].astype(float)
    return df

# ────────────────────────────────────────────────
# 선적(이동) 데이터 처리 (Transfers)
# ────────────────────────────────────────────────

def fetch_transfers() -> pd.DataFrame:
    """
    Supabase에서 선적/이동 내역을 가져옵니다.
    """
    supabase = get_supabase()
    response = supabase.table("transfers").select("*").order("created_at", desc=True).execute()
    
    if not response.data:
        return pd.DataFrame(columns=["id", "상품코드", "출발지", "도착지", "선적수량", "선적일", "하차예정일", "상태", "생성일"])
        
    df = pd.DataFrame(response.data)
    
    # 컬럼명 매핑 (앱 내에서 구글 시트 기반 컬럼과 호환되도록)
    df = df.rename(columns={
        "product_code": "상품코드",
        "source": "출발지",
        "destination": "도착지",
        "quantity": "선적수량",
        "departure_date": "선적일",
        "arrival_date": "하차예정일",
        "status": "상태",
        "created_at": "생성일"
    })
    
    df["선적일"] = pd.to_datetime(df["선적일"], errors="coerce").dt.date
    df["하차예정일"] = pd.to_datetime(df["하차예정일"], errors="coerce").dt.date
    df["선적수량"] = pd.to_numeric(df["선적수량"], errors="coerce").fillna(0)
    
    return df

def insert_transfer(product_code: str, source: str, destination: str, quantity: float, departure_date: str, arrival_date: str):
    """
    새로운 선적/이동 지시를 Supabase에 저장합니다.
    """
    supabase = get_supabase()
    data = {
        "product_code": product_code,
        "source": source,
        "destination": destination,
        "quantity": quantity,
        "departure_date": departure_date,
        "arrival_date": arrival_date,
        "status": "이동중"
    }
    supabase.table("transfers").insert(data).execute()

def update_transfer_status(transfer_id: str, status: str):
    """
    특정 선적의 상태를 업데이트합니다 (예: '이동중' -> '입고완료').
    """
    supabase = get_supabase()
    supabase.table("transfers").update({"status": status}).eq("id", transfer_id).execute()
