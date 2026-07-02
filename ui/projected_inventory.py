import streamlit as st
import pandas as pd
from datetime import date, timedelta
import math

def calculate_daily_velocity(shipping_df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """최근 N일간의 일평균 출고량을 채널별/상품코드별로 계산"""
    if shipping_df is None or shipping_df.empty:
        return pd.DataFrame(columns=["채널", "상품코드", "일평균출고량"])
        
    cutoff_date = date.today() - timedelta(days=days)
    recent_ship = shipping_df[
        pd.to_datetime(shipping_df["주문일시"]).dt.date >= cutoff_date
    ]
    
    if recent_ship.empty:
        return pd.DataFrame(columns=["채널", "상품코드", "일평균출고량"])
        
    agg = recent_ship.groupby(["채널", "상품코드"])["수량"].sum().reset_index()
    agg["일평균출고량"] = agg["수량"] / days
    return agg[["채널", "상품코드", "일평균출고량"]]


def render_projected_inventory(
    master_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    shipping_df: pd.DataFrame,
    po_df: pd.DataFrame,
    transfer_df: pd.DataFrame,
    sim_days: int = 180
):
    st.markdown('<div class="sec-title">🌐 다단계 예상재고 흐름 (Projected Inventory)</div>', unsafe_allow_html=True)
    st.info("현재고, 일평균 출고량, 발주 납기일(국내 입고), 선적일(국내 출고), 하차예정일(해외 입고) 데이터를 종합하여 향후 재고 흐름을 시뮬레이션합니다.")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        selected_code = st.selectbox(
            "시뮬레이션할 상품 선택",
            options=master_df["상품코드"].tolist(),
            format_func=lambda c: f"{c} - {master_df[master_df['상품코드']==c]['상품명'].iloc[0]}"
        )
        velocity_days = st.slider("평균 출고량 산출 기간 (최근 N일)", 7, 90, 30)
    
    if not selected_code:
        return

    # 1. 일평균 출고량 계산
    velocity_df = calculate_daily_velocity(shipping_df, days=velocity_days)
    
    # 한국(CK로지스) 및 미국(US 창고) 속도 추출
    kr_velocity = 0.0
    us_velocity = 0.0
    
    v_kr = velocity_df[(velocity_df["상품코드"] == selected_code) & (velocity_df["채널"] == "CK로지스")]
    v_us = velocity_df[(velocity_df["상품코드"] == selected_code) & (velocity_df["채널"] == "US 창고")]
    
    if not v_kr.empty: kr_velocity = v_kr["일평균출고량"].iloc[0]
    if not v_us.empty: us_velocity = v_us["일평균출고량"].iloc[0]

    with col2:
        st.markdown(f"**현재 일평균 출고량 추세 (최근 {velocity_days}일 기준)**")
        st.markdown(f"- 🇰🇷 한국 (CK로지스): **하루 약 {kr_velocity:.1f}개** 출고")
        st.markdown(f"- 🇺🇸 미국 (US 창고): **하루 약 {us_velocity:.1f}개** 출고")

    st.divider()

    # 2. 현재고 추출
    kr_inv = 0
    us_inv = 0
    if not inventory_df.empty:
        inv_kr = inventory_df[(inventory_df["상품코드"] == selected_code) & (inventory_df["채널"] == "CK로지스")]
        inv_us = inventory_df[(inventory_df["상품코드"] == selected_code) & (inventory_df["채널"] == "US 창고")]
        if not inv_kr.empty: kr_inv = inv_kr["현재고"].sum()
        if not inv_us.empty: us_inv = inv_us["현재고"].sum()

    # 3. 이벤트 타임라인 구축
    events = {}
    today = date.today()
    
    # PO 입고 이벤트 (한국)
    if po_df is not None and not po_df.empty:
        po_sub = po_df[(po_df["상품코드"] == selected_code) & (~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False))]
        for _, row in po_sub.iterrows():
            d = row["납기예정일"]
            if pd.isna(d): continue
            if d not in events: events[d] = {"kr_in": 0, "kr_out": 0, "us_in": 0}
            events[d]["kr_in"] += row["발주수량"]

    # 선적 이동 이벤트 (한국 출고, 미국 입고)
    if transfer_df is not None and not transfer_df.empty:
        tr_sub = transfer_df[
            (transfer_df["상품코드"] == selected_code) & 
            (~transfer_df["상태"].str.replace(" ", "").str.contains("입고완료|완료", na=False))
        ]
        for _, row in tr_sub.iterrows():
            depart_d = row["선적일"]
            arrive_d = row["하차예정일"]
            qty = row["선적수량"]
            
            if pd.notna(depart_d):
                if depart_d not in events: events[depart_d] = {"kr_in": 0, "kr_out": 0, "us_in": 0}
                events[depart_d]["kr_out"] += qty
                
            if pd.notna(arrive_d):
                if arrive_d not in events: events[arrive_d] = {"kr_in": 0, "kr_out": 0, "us_in": 0}
                events[arrive_d]["us_in"] += qty

    # 4. 일자별 시뮬레이션
    sim_data = []
    curr_kr = float(kr_inv)
    curr_us = float(us_inv)
    in_transit = 0.0
    
    # 과거 선적되었으나 아직 도착하지 않은 수량을 찾기 위함
    # transfer_df에서 선적일은 지났는데 하차예정일이 안 온 경우
    if transfer_df is not None and not transfer_df.empty:
        past_depart = transfer_df[
            (transfer_df["상품코드"] == selected_code) & 
            (pd.to_datetime(transfer_df["선적일"]).dt.date <= today) &
            (pd.to_datetime(transfer_df["하차예정일"]).dt.date > today) &
            (~transfer_df["상태"].str.replace(" ", "").str.contains("입고완료|완료", na=False))
        ]
        in_transit = past_depart["선적수량"].sum()

    for i in range(sim_days):
        current_date = today + timedelta(days=i)
        
        # 데일리 출고 차감 (매일 발생)
        curr_kr -= kr_velocity
        curr_us -= us_velocity
        
        # 이벤트 발생 (입/출고)
        ev_kr_in = 0
        ev_kr_out = 0
        ev_us_in = 0
        
        if current_date in events:
            ev = events[current_date]
            ev_kr_in = ev["kr_in"]
            ev_kr_out = ev["kr_out"]
            ev_us_in = ev["us_in"]
            
            curr_kr += ev_kr_in
            curr_kr -= ev_kr_out
            in_transit += ev_kr_out
            
            curr_us += ev_us_in
            in_transit -= ev_us_in
            if in_transit < 0: in_transit = 0
            
        sim_data.append({
            "날짜": current_date,
            "한국 예상재고(CK)": math.floor(curr_kr),
            "미국 예상재고(US)": math.floor(curr_us),
            "이동중(In-Transit)": math.floor(in_transit),
            "이벤트": []
        })
        
        # 이벤트 기록
        evt_strs = []
        if ev_kr_in > 0: evt_strs.append(f"발주입고 +{ev_kr_in:,.0f}")
        if ev_kr_out > 0: evt_strs.append(f"선적출고 -{ev_kr_out:,.0f}")
        if ev_us_in > 0: evt_strs.append(f"해외도착 +{ev_us_in:,.0f}")
        sim_data[-1]["이벤트"] = " | ".join(evt_strs)

    sim_df = pd.DataFrame(sim_data)
    
    # OOS (Out of Stock) 경고
    kr_oos_dates = sim_df[sim_df["한국 예상재고(CK)"] < 0]
    us_oos_dates = sim_df[sim_df["미국 예상재고(US)"] < 0]
    
    if not kr_oos_dates.empty or not us_oos_dates.empty:
        msg = "⚠️ **품절(OOS) 예상 경보**\n"
        if not kr_oos_dates.empty:
            msg += f"- 한국(CK로지스): {kr_oos_dates.iloc[0]['날짜']} 부터 재고 소진 예상\n"
        if not us_oos_dates.empty:
            msg += f"- 미국(US 창고): {us_oos_dates.iloc[0]['날짜']} 부터 재고 소진 예상\n"
        st.error(msg)
    else:
        st.success(f"✅ 향후 {sim_days}일 동안 한국과 미국 모두 품절 예상일이 없습니다.")

    # 차트 그리기
    st.markdown("#### 📈 향후 6개월 예상재고 흐름")
    chart_data = sim_df.set_index("날짜")[["한국 예상재고(CK)", "미국 예상재고(US)", "이동중(In-Transit)"]]
    st.line_chart(chart_data, color=["#4CAF50", "#2196F3", "#9E9E9E"])
    
    # 데이터 표
    st.markdown("#### 🗓️ 일자별 상세 시뮬레이션 내역")
    # 이벤트가 있는 날짜나 매월 1일만 필터링하거나 전체를 보여주기
    show_all = st.checkbox("전체 일자 보기", value=False)
    if show_all:
        view_df = sim_df
    else:
        # 이벤트가 있거나 현재고가 마이너스인 일자, 혹은 매월 1일
        view_df = sim_df[
            (sim_df["이벤트"] != "") | 
            (sim_df["한국 예상재고(CK)"] < 0) | 
            (sim_df["미국 예상재고(US)"] < 0) |
            (pd.to_datetime(sim_df["날짜"]).dt.day == 1)
        ]
        
    st.dataframe(view_df.style.applymap(
        lambda x: "color: red; font-weight: bold;" if isinstance(x, (int, float)) and x < 0 else "",
        subset=["한국 예상재고(CK)", "미국 예상재고(US)"]
    ), use_container_width=True)
