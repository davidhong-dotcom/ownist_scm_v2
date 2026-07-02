"""
ui/sop_simulation.py
--------------------
S&OP 생산량 시뮬레이션 UI 및 로직
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
from data.processor import safe_divide, _calc_expiry

def render_sop_simulation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, po_df: pd.DataFrame, today: date):
    st.markdown('<div class="sec-title">🔮 S&OP 생산량 시뮬레이션</div>', unsafe_allow_html=True)
    
    if master_df is None or inventory_df is None or shipping_df is None or shipping_df.empty:
        st.info("데이터가 충분하지 않아 시뮬레이션을 실행할 수 없습니다. 데이터를 먼저 불러와 주세요.")
        return
        
    st.markdown("""
    <div class="info-box">
    <strong>💡 시뮬레이션 설명</strong><br>
    최근 90일간의 일평균 출고량(Run-Rate)을 바탕으로 현재고의 <strong>예상 소진일</strong>을 예측하고, 
    목표로 하는 <strong>안전재고 일수</strong>를 설정했을 때 필요한 <strong>발주/생산 필요량</strong>을 시뮬레이션합니다.
    </div>
    """, unsafe_allow_html=True)
    
    # ── 설정 영역 ──
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        safety_multiplier = st.number_input("목표 안전재고 배수", min_value=0.0, max_value=10.0, value=1.5, step=0.1,
                               help="직전 3개월(당월 제외) 월평균 출고량에 곱할 배수입니다. (기본값 1.5)")
    with col2:
        lead_time = st.number_input("생산 리드타임 (일)", min_value=0, max_value=180, value=45, step=1,
                                  help="발주 후 입고까지 걸리는 예상 일수입니다.")
        
    st.divider()
    
    # ── 데이터 전처리 ──
    # 당월 제외 직전 3개월 계산 (예: 7월이면 4월 1일 ~ 6월 30일)
    current_month_start = today.replace(day=1)
    past_3_months_end = current_month_start - timedelta(days=1)
    past_3_months_start = (past_3_months_end.replace(day=1) - timedelta(days=60)).replace(day=1)
    
    recent = shipping_df[(shipping_df["출고일자"] >= past_3_months_start) & (shipping_df["출고일자"] <= past_3_months_end)]
    recent_agg = recent.groupby("상품코드", as_index=False)["출고수량"].sum().rename(columns={"출고수량": "직전3개월총출고량"})
    
    # 전창고(채널) 재고 통합 및 마스터DB 중복 제거
    unique_master = master_df.drop_duplicates(subset=["상품코드"]).copy()
    inv_agg = inventory_df.groupby("상품코드", as_index=False)["현재고"].sum()
    
    df = unique_master.merge(inv_agg, on="상품코드", how="left")
    df = df.merge(recent_agg, on="상품코드", how="left")
    
    # 지정된 품목구분만 필터링 (S&OP 시뮬레이션 대상 한정)
    if "품목구분" in df.columns:
        target_categories = ["트리플콜라겐", "트리플샤인", "케라그로우"]
        df = df[df["품목구분"].isin(target_categories)].copy()
    
    df["현재고"] = df["현재고"].fillna(0)
    df["직전3개월총출고량"] = df["직전3개월총출고량"].fillna(0)
    
    # 직전 3개월 월평균 및 일평균 출고량
    df["월평균출고량"] = df["직전3개월총출고량"] / 3
    df["일평균출고량"] = df["직전3개월총출고량"] / 90
    
    # ── 시뮬레이션 산출 로직 ──
    # 현재 사용가능 일수 및 예상소진일
    df["현재_사용가능일"] = df.apply(lambda r: safe_divide(r["현재고"], r["일평균출고량"]), axis=1)
    df["예상소진일"] = df["현재_사용가능일"].apply(lambda v: _calc_expiry(v, today))
    
    # 목표 재고(안전재고) = 월평균출고량 * 안전재고 배수
    df["안전재고량"] = df["월평균출고량"] * safety_multiplier
    
    # 발주 필요일정 = 예상소진일 - 리드타임
    from datetime import datetime
    def _calc_order_date(expiry_str, lt):
        if expiry_str in ["출고없음", "∞", "-"]:
            return expiry_str
        try:
            d = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            return (d - timedelta(days=int(lt))).strftime("%Y-%m-%d")
        except:
            return expiry_str
            
    df["발주_필요일정"] = df["예상소진일"].apply(lambda x: _calc_order_date(x, lead_time))
    
    # 발주/입고 예정 수량 산출 (완료되지 않은 건만)
    if po_df is not None and not po_df.empty:
        pending_po = po_df[~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False)]
        pending_agg = pending_po.groupby("상품코드", as_index=False)["발주수량"].sum().rename(columns={"발주수량": "입고예정수량"})
        df = df.merge(pending_agg, on="상품코드", how="left")
    else:
        df["입고예정수량"] = 0
        
    df["입고예정수량"] = df.get("입고예정수량", 0).fillna(0)
    
    # 필요 생산량 = 안전재고량 - (현재고 + 입고예정수량) + (리드타임 동안의 예상 출고량)
    df["총_필요생산량"] = df["안전재고량"] - (df["현재고"] + df["입고예정수량"]) + (df["일평균출고량"] * lead_time)
    df["총_필요생산량"] = df["총_필요생산량"].apply(lambda x: x if x > 0 else 0)
    
    # ── 표시용 테이블 ──
    cols = ["상품구분", "상품코드", "상품명", "현재고", "입고예정수량", "월평균출고량", "일평균출고량", "안전재고량", "예상소진일", "발주_필요일정", "총_필요생산량"]
    if "품목구분" in df.columns:
        cols[0] = "품목구분"
    elif "구분" in df.columns:
        cols[0] = "구분"
        
    display = df[cols].copy()
    
    # 소수점 반올림
    num_cols = ["현재고", "입고예정수량", "월평균출고량", "일평균출고량", "안전재고량", "총_필요생산량"]
    for c in num_cols:
        display[c] = display[c].apply(lambda x: np.ceil(x) if isinstance(x, (int, float)) else x)
    
    # 내림차순 정렬
    display = display.sort_values("총_필요생산량", ascending=False).reset_index(drop=True)
    
    # 행 하이라이트 (발주 필요일정이 지났거나 임박(7일 이내)한 경우)
    def _highlight(row):
        try:
            val = row["발주_필요일정"]
            if val not in ["출고없음", "∞", "-"]:
                order_d = datetime.strptime(val, "%Y-%m-%d").date()
                if (order_d - today).days <= 7:
                    return ["background-color:#fee2e2;color:#b91c1c;"] * len(row)
        except:
            pass
        return [""] * len(row)
        
    styled = display.style.apply(_highlight, axis=1).format({
        "현재고": "{:,.0f}",
        "입고예정수량": "{:,.0f}",
        "월평균출고량": "{:,.0f}",
        "일평균출고량": "{:,.0f}",
        "안전재고량": "{:,.0f}",
        "총_필요생산량": "{:,.0f}"
    })
    
    # 포맷팅
    st.dataframe(styled, use_container_width=True, height=500)
    
    # 합계 요약
    total_need = display["총_필요생산량"].sum()
    st.markdown(f"**전체 시뮬레이션 결과: 총 {total_need:,.0f}개의 필요 생산량이 산출되었습니다.**")
    
    csv = display.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ 시뮬레이션 결과 CSV 다운로드",
        data=csv,
        file_name=f"SOP_시뮬레이션_{today.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    # ── 품목별 총 생산수량(스틱 단위) 산출 ──
    st.divider()
    st.markdown('<div class="sec-title">🏭 품목별 총 생산수량(스틱 단위) 산출</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    <strong>💡 안내</strong><br>
    본품 자체가 스틱 단위로 동일하므로, 동일한 카테고리(품목구분)를 공유하는 여러 제품군(내수용/수출용 등)의 필요생산량에 
    <strong>내포입</strong>을 곱하여 <strong>OEM 제조사에 일괄 발주할 스틱 단위 총 생산수량</strong>을 계산합니다.
    </div>
    """, unsafe_allow_html=True)
    
    cat_col = "품목구분" if "품목구분" in df.columns else "구분" if "구분" in df.columns else None
    
    if cat_col and "내포입" in df.columns:
        df["내포입"] = pd.to_numeric(df["내포입"], errors="coerce").fillna(1)
        df["총 필요생산량(스틱 단위)"] = df["총_필요생산량"] * df["내포입"]
        
        agg_df = df.groupby(cat_col, as_index=False)["총 필요생산량(스틱 단위)"].sum()
        agg_df = agg_df[agg_df["총 필요생산량(스틱 단위)"] > 0].sort_values("총 필요생산량(스틱 단위)", ascending=False).reset_index(drop=True)
        
        if not agg_df.empty:
            agg_styled = agg_df.style.format({"총 필요생산량(스틱 단위)": "{:,.0f}"})
            st.dataframe(agg_styled, use_container_width=True)
        else:
            st.info("통합 발주가 필요한 생산수량이 없습니다.")
    else:
        st.info("마스터 DB에 '품목구분' 또는 '내포입' 컬럼이 없어 계산할 수 없습니다. 데이터 설정에서 마스터 DB를 다시 로드해주세요.")
