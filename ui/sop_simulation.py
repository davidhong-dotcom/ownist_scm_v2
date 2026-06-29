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

def render_sop_simulation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, today: date):
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
        target_days = st.slider("목표 안전재고 일수", min_value=15, max_value=180, value=60, step=15,
                               help="현재고 + 필요 생산량으로 버틸 수 있는 목표 일수입니다.")
    with col2:
        lead_time = st.number_input("생산 리드타임 (일)", min_value=0, max_value=100, value=14, step=1,
                                  help="발주 후 입고까지 걸리는 예상 일수입니다.")
        
    st.divider()
    
    # ── 데이터 전처리 ──
    # 최근 90일 기준 일평균 출고량 산출
    cutoff = today - timedelta(days=90)
    recent = shipping_df[(shipping_df["출고일자"] >= cutoff) & (shipping_df["출고일자"] <= today)]
    recent_agg = recent.groupby("상품코드", as_index=False)["출고수량"].sum().rename(columns={"출고수량": "90일출고량"})
    
    df = master_df.merge(inventory_df, on="상품코드", how="left")
    df = df.merge(recent_agg, on="상품코드", how="left")
    
    df["현재고"] = df["현재고"].fillna(0)
    df["90일출고량"] = df["90일출고량"].fillna(0)
    df["일평균출고량"] = df["90일출고량"] / 90
    
    # ── 시뮬레이션 산출 로직 ──
    # 현재 사용가능 일수
    df["현재_사용가능일"] = df.apply(lambda r: safe_divide(r["현재고"], r["일평균출고량"]), axis=1)
    df["예상소진일"] = df["현재_사용가능일"].apply(lambda v: _calc_expiry(v, today))
    
    # 목표 재고 = 목표 안전재고 일수 * 일평균출고량
    df["목표재고량"] = df["일평균출고량"] * target_days
    
    # 필요 생산량 = 목표재고량 - 현재고 + (리드타임 동안의 예상 출고량)
    # 리드타임 동안의 출고량 반영 (발주 시점부터 입고 시점까지 재고가 추가로 소진됨)
    df["필요생산량"] = df["목표재고량"] - df["현재고"] + (df["일평균출고량"] * lead_time)
    
    # 필요생산량이 0보다 작으면 0으로 처리 (재고 충분)
    df["필요생산량"] = df["필요생산량"].apply(lambda x: x if x > 0 else 0)
    
    # ── 표시용 테이블 ──
    cols = ["상품구분", "상품코드", "상품명", "현재고", "일평균출고량", "현재_사용가능일", "예상소진일", "목표재고량", "필요생산량"]
    if "품목구분" in df.columns:
        cols[0] = "품목구분"
    elif "구분" in df.columns:
        cols[0] = "구분"
        
    display = df[cols].copy()
    
    # 소수점 반올림 및 포맷팅
    num_cols = ["현재고", "일평균출고량", "목표재고량", "필요생산량"]
    for c in num_cols:
        display[c] = display[c].apply(lambda x: np.ceil(x) if isinstance(x, (int, float)) else x)
    
    display["현재_사용가능일"] = display["현재_사용가능일"].apply(
        lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else v
    )
    
    # 필요생산량 내림차순 정렬
    display = display.sort_values("필요생산량", ascending=False).reset_index(drop=True)
    
    # 행 하이라이트 (현재 사용가능일이 리드타임보다 적으면 빨간색)
    def _highlight(row):
        try:
            val = row["현재_사용가능일"]
            if isinstance(val, str):
                val = float(val)
            if isinstance(val, (int, float)) and val < lead_time:
                return ["background-color:#fee2e2;color:#b91c1c;"] * len(row)
        except Exception:
            pass
        return [""] * len(row)
        
    styled = display.style.apply(_highlight, axis=1)
    
    # 포맷팅
    st.dataframe(styled, use_container_width=True, height=500)
    
    # 합계 요약
    total_need = display["필요생산량"].sum()
    st.markdown(f"**전체 시뮬레이션 결과: 총 {total_need:,.0f}개의 필요 생산량이 산출되었습니다.**")
    
    csv = display.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ 시뮬레이션 결과 CSV 다운로드",
        data=csv,
        file_name=f"SOP_시뮬레이션_{today.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
