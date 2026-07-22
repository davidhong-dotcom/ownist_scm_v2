import streamlit as st
import pandas as pd
from datetime import date
from data.supabase_client import fetch_transfers, insert_transfer, update_transfer_status, update_transfer_remarks, update_transfer_details
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
                transport_method = st.selectbox("운송 방식", ["선적", "항공"])
            with col2:
                departure_date = st.date_input("선적일 (출발일)", value=date.today())
                arrival_date = st.date_input("하차예정일 (도착예정일)", value=date.today())
                destination = st.text_input("도착지", value="CGETC")
                remarks = st.text_input("특이사항 (선택)", placeholder="예) FDA 승인 대기중")
                
            submitted = st.form_submit_button("선적 등록", use_container_width=True)
            if submitted:
                try:
                    insert_transfer(
                        selected_code,
                        source,
                        destination,
                        qty,
                        departure_date.strftime("%Y-%m-%d"),
                        arrival_date.strftime("%Y-%m-%d"),
                        remarks,
                        transport_method
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
                is_edit = st.session_state.get(f"edit_mode_{row['id']}", False)
                
                with c2:
                    if is_edit:
                        edit_source = st.text_input("출발지", value=str(row['출발지']), key=f"esrc_{row['id']}")
                        edit_destination = st.text_input("도착지", value=str(row['도착지']), key=f"edest_{row['id']}")
                        cur_method = str(row.get('운송방식', '선적'))
                        edit_transport = st.selectbox("운송 방식", ["선적", "항공"], index=0 if cur_method == "선적" else 1, key=f"etrans_{row['id']}")
                    else:
                        t_icon = "✈️" if row.get("운송방식") == "항공" else "🚢"
                        t_method = str(row.get('운송방식', '선적'))
                        st.markdown(f"🛫 **{row['출발지']}** ({row['선적일']})<br>🛬 **{row['도착지']}** ({row['하차예정일']})<br>{t_icon} {t_method}", unsafe_allow_html=True)
                
                with c3:
                    if is_edit:
                        edit_qty = st.number_input("수량", min_value=1, step=1, value=int(row['선적수량']) if pd.notna(row['선적수량']) else 1000, key=f"eqty_{row['id']}")
                        edit_dep = st.date_input("선적일", value=pd.to_datetime(row['선적일']).date() if pd.notna(row['선적일']) else date.today(), key=f"edep_{row['id']}")
                        edit_arr = st.date_input("하차예정일", value=pd.to_datetime(row['하차예정일']).date() if pd.notna(row['하차예정일']) else date.today(), key=f"earr_{row['id']}")
                    else:
                        c3_1, c3_2 = st.columns([7, 3])
                        with c3_1:
                            st.markdown(f"📦 수량: **{row['선적수량']:,.0f}**")
                            st.markdown(f"상태: 🟠 **{row['상태']}**")
                        with c3_2:
                            if st.button("✏️", key=f"edit_btn_{row['id']}", help="내역 수정"):
                                st.session_state[f"edit_mode_{row['id']}"] = True
                                st.rerun()
                                
                with c4:
                    if is_edit:
                        if st.button("💾 저장", key=f"save_btn_{row['id']}", use_container_width=True):
                            try:
                                updates = {
                                    "source": edit_source,
                                    "destination": edit_destination,
                                    "quantity": edit_qty,
                                    "departure_date": edit_dep.strftime("%Y-%m-%d"),
                                    "arrival_date": edit_arr.strftime("%Y-%m-%d"),
                                    "transport_method": edit_transport
                                }
                                update_transfer_details(row['id'], updates)
                                st.session_state[f"edit_mode_{row['id']}"] = False
                                st.session_state["transfer_df"] = fetch_transfers()
                                st.rerun()
                            except Exception as e:
                                render_error(f"수정 실패: {e}")
                        if st.button("❌ 취소", key=f"cancel_btn_{row['id']}", use_container_width=True):
                            st.session_state[f"edit_mode_{row['id']}"] = False
                            st.rerun()
                    else:
                        if st.button("✅ 도착(입고완료) 처리", key=f"btn_done_{row['id']}", use_container_width=True):
                            try:
                                update_transfer_status(row['id'], "입고완료")
                                st.session_state["transfer_df"] = fetch_transfers()
                                st.rerun()
                            except Exception as e:
                                render_error(f"상태 업데이트 실패: {e}")
                
                # 특이사항 입력 영역 (편집 모드가 아닐 때만 표시)
                if not is_edit:
                    remarks_val = row.get('특이사항', '')
                    col_rem1, col_rem2 = st.columns([5, 1])
                    with col_rem1:
                        new_remarks = st.text_input("특이사항", value=remarks_val if pd.notna(remarks_val) else "", key=f"rem_in_{row['id']}", label_visibility="collapsed", placeholder="특이사항 작성 (예: FDA 승인 대기중)")
                    with col_rem2:
                        if st.button("저장", key=f"rem_btn_{row['id']}", use_container_width=True):
                            try:
                                update_transfer_remarks(row['id'], new_remarks)
                                st.session_state["transfer_df"] = fetch_transfers()
                                st.rerun()
                            except Exception as e:
                                render_error(f"특이사항 업데이트 실패: {e}")
                
                st.markdown("<hr style='margin: 0.5rem 0;'>", unsafe_allow_html=True)
    else:
        st.write("현재 이동 중인 재고가 없습니다.")

    st.markdown("#### ✅ 과거 입고 완료 내역")
    if not completed_df.empty:
        with st.expander("입고 완료 내역 보기", expanded=False):
            st.dataframe(completed_df[["선적일", "하차예정일", "상품명", "출발지", "도착지", "선적수량", "상태"]], use_container_width=True)
    else:
        st.caption("완료된 내역이 없습니다.")
