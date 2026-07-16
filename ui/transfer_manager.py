import streamlit as st
import pandas as pd
from datetime import date
from data.supabase_client import fetch_transfers, insert_transfer, update_transfer_status
from ui.components import render_success, render_error

def render_transfer_manager(master_df: pd.DataFrame):
    st.markdown('<div class="sec-title">🚢 선적 및 재고이동 관리</div>', unsafe_allow_html=True)
    st.info("국내 창고에서 해외(또는 타 채널)로 이동하는 재고를 추적하고 입고 처리할 수 있습니다.")
    
    # 1. 신규 선적 등록 (UI Form)
    with st.expander("➕ 새로운 선적(이동) 지시 등록", expanded=False):
        with st.form("new_transfer_form"):
            col1, col2 = st.columns(2)
            with col1:
                selected_code = st.selectbox(
                    "상품 선택",
                    options=master_df["상품코드"].tolist(),
                    format_func=lambda c: f"{c} - {master_df[master_df['상품코드']==c]['상품명'].iloc[0]}"
                )
                source = st.text_input("출발지", value="CK로지스")
                qty = st.number_input("선적 수량", min_value=1, step=1, value=1000)
            with col2:
                departure_date = st.date_input("선적일 (출발일)", value=date.today())
                arrival_date = st.date_input("하차예정일 (도착예정일)", value=date.today())
                destination = st.text_input("도착지", value="CGETC")
                
            submitted = st.form_submit_button("선적 등록", use_container_width=True)
            if submitted:
                try:
                    insert_transfer(
                        selected_code,
                        source,
                        destination,
                        qty,
                        departure_date.strftime("%Y-%m-%d"),
                        arrival_date.strftime("%Y-%m-%d")
                    )
                    st.session_state["transfer_df"] = fetch_transfers()
                    render_success("새로운 선적 내역이 등록되었습니다!")
                except Exception as e:
                    render_error(f"등록 실패: {e}")

    st.divider()
    
    # 2. 이동 내역 리스트
    st.markdown("#### 📋 선적 진행 내역 (In-Transit)")
    
    transfer_df = st.session_state.get("transfer_df")
    if transfer_df is None:
        try:
            st.session_state["transfer_df"] = fetch_transfers()
            transfer_df = st.session_state["transfer_df"]
        except Exception as e:
            render_error("Supabase에서 데이터를 가져올 수 없습니다. 'transfers' 테이블을 먼저 생성했는지 확인해주세요.")
            return

    if transfer_df.empty:
        st.info("진행 중이거나 완료된 선적 내역이 없습니다.")
        return

    # 상품명 조인
    disp_df = transfer_df.merge(master_df[["상품코드", "상품명"]], on="상품코드", how="left")
    
    # "진행중" 데이터와 "완료" 데이터 분리
    in_transit_df = disp_df[~disp_df["상태"].str.replace(" ", "").str.contains("입고완료|완료", na=False)]
    completed_df = disp_df[disp_df["상태"].str.replace(" ", "").str.contains("입고완료|완료", na=False)]

    if not in_transit_df.empty:
        for _, row in in_transit_df.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
                with c1:
                    st.markdown(f"**{row['상품코드']}**")
                    st.caption(f"{row['상품명']}")
                with c2:
                    st.markdown(f"🛫 **{row['출발지']}** ({row['선적일']})<br>🛬 **{row['도착지']}** ({row['하차예정일']})", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"📦 수량: **{row['선적수량']:,.0f}**")
                    st.markdown(f"상태: 🟠 **{row['상태']}**")
                with c4:
                    if st.button("✅ 도착(입고완료) 처리", key=f"btn_done_{row['id']}", use_container_width=True):
                        try:
                            update_transfer_status(row['id'], "입고완료")
                            st.session_state["transfer_df"] = fetch_transfers()
                            st.rerun()
                        except Exception as e:
                            render_error(f"상태 업데이트 실패: {e}")
                st.markdown("<hr style='margin: 0.5rem 0;'>", unsafe_allow_html=True)
    else:
        st.write("현재 이동 중인 재고가 없습니다.")

    st.markdown("#### ✅ 과거 입고 완료 내역")
    if not completed_df.empty:
        with st.expander("입고 완료 내역 보기", expanded=False):
            st.dataframe(completed_df[["선적일", "하차예정일", "상품명", "출발지", "도착지", "선적수량", "상태"]], use_container_width=True)
    else:
        st.caption("완료된 내역이 없습니다.")
