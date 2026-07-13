"""
ui/sop_simulation.py
--------------------
S&OP 생산량 시뮬레이션 UI 및 로직
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
from data.processor import safe_divide, _calc_expiry

def render_sop_simulation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, po_df: pd.DataFrame, today: date):
    st.markdown('<div class="sec-title">🔮 S&OP 라이브 시뮬레이션</div>', unsafe_allow_html=True)
    
    if master_df is None or inventory_df is None or shipping_df is None or shipping_df.empty:
        st.info("데이터가 충분하지 않아 시뮬레이션을 실행할 수 없습니다. 데이터를 먼저 불러와 주세요.")
        return
        
    st.markdown("""
    <div class="info-box">
    <strong>💡 시뮬레이션 설명</strong><br>
    최근 90일간의 일평균 출고량(Run-Rate)을 바탕으로 현재고의 <strong>예상 소진일</strong>을 예측하고, 
    목표로 하는 <strong>안전재고 일수</strong>를 설정했을 때 필요한 <strong>발주/생산 필요량</strong>을 시뮬레이션합니다.<br>
    ✅ <strong>테이블의 ✏️ 기호가 있는 열의 수치를 더블클릭하여 자유롭게 수정해 보세요!</strong> (회의 중 실시간 조율)
    </div>
    """, unsafe_allow_html=True)
    
    # ── 설정 영역 (공통 초기값) ──
    col1, col2, col3 = st.columns([1, 1, 1.5])
    
    with col1:
        default_safety = st.number_input("기본 목표 안전재고 배수", min_value=0.0, max_value=10.0, value=1.5, step=0.1,
                               help="초기 세팅할 기본 안전재고 배수입니다.")
    with col2:
        default_lead = st.number_input("기본 생산 리드타임(일)", min_value=0, max_value=180, value=45, step=1,
                                   help="발주 후 입고까지 걸리는 예상 일수입니다.")
    with col3:
        demand_factor = st.slider("📈 수요 증감 시나리오 (%)", min_value=-50, max_value=100, value=0, step=5,
                                  help="직전 3개월 월평균 출고량 대비 앞으로의 수요 증감률을 일괄 가정합니다.")
                                  
    col4, col5, col_btn = st.columns([1.5, 1, 1])
    with col4:
        global_moq = st.number_input("스틱/포 기본 MOQ", min_value=0, max_value=1000000, value=300000, step=50000, help="내용물(벌크) 생산 최소 수량입니다.")
    with col5:
        st.markdown("<br>", unsafe_allow_html=True)
        auto_moq = st.checkbox("MOQ 본품 자동 보정", value=True, help="체험키트 등 소량 발주 시 MOQ를 맞추기 위해 본품 산출량을 올립니다.")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 초기화", use_container_width=True):
            if "sop_overrides" in st.session_state:
                del st.session_state["sop_overrides"]
            st.rerun()

    st.divider()

    # ── 세션 상태 초기화 (에디터 오버라이드용) ──
    if "sop_overrides" not in st.session_state:
        st.session_state["sop_overrides"] = {}

    # ── 콜백 함수: 에디터에서 수정한 값을 Session State에 저장 ──
    def on_editor_change():
        edits = st.session_state.get("sop_data_editor", {}).get("edited_rows", {})
        codes = st.session_state.get("sop_product_codes", [])
        
        for row_idx_str, changes in edits.items():
            row_idx = int(row_idx_str)
            if row_idx < len(codes):
                code = codes[row_idx]
                if code not in st.session_state["sop_overrides"]:
                    st.session_state["sop_overrides"][code] = {}
                for col, val in changes.items():
                    st.session_state["sop_overrides"][code][col] = val

    # ── 데이터 전처리 ──
    current_month_start = today.replace(day=1)
    past_3_months_end = current_month_start - timedelta(days=1)
    past_3_months_start = (past_3_months_end.replace(day=1) - timedelta(days=60)).replace(day=1)
    
    recent = shipping_df[(shipping_df["출고일자"] >= past_3_months_start) & (shipping_df["출고일자"] <= past_3_months_end)]
    recent_agg = recent.groupby("상품코드", as_index=False)["출고수량"].sum().rename(columns={"출고수량": "직전3개월총출고량"})
    
    unique_master = master_df.drop_duplicates(subset=["상품코드"]).copy()
    inv_agg = inventory_df.groupby("상품코드", as_index=False)["현재고"].sum()
    
    df = unique_master.merge(inv_agg, on="상품코드", how="left")
    df = df.merge(recent_agg, on="상품코드", how="left")
    
    if "품목구분" in df.columns:
        target_categories = ["트리플콜라겐", "트리플샤인", "케라그로우"]
        df = df[df["품목구분"].isin(target_categories)].copy()
    
    df["현재고"] = df["현재고"].fillna(0)
    df["직전3개월총출고량"] = df["직전3개월총출고량"].fillna(0)
    
    # 발주/입고 예정 수량 산출 (완료되지 않은 건만)
    if po_df is not None and not po_df.empty:
        pending_po = po_df[~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False)]
        pending_agg = pending_po.groupby("상품코드", as_index=False)["발주수량"].sum().rename(columns={"발주수량": "입고예정수량"})
        df = df.merge(pending_agg, on="상품코드", how="left")
    else:
        df["입고예정수량"] = 0
        
    df["입고예정수량"] = df.get("입고예정수량", 0).fillna(0)
    
    # 초기 계산
    df["월평균_실적"] = df["직전3개월총출고량"] / 3
    
    # ── 입력값 (오버라이드) 반영 ──
    # 1. 수요 증감 시나리오 기본 반영
    df["조정_월평균출고량"] = df["월평균_실적"] * (1 + demand_factor / 100)
    
    # 마스터 DB에 안전재고/리드타임이 있으면 그것을 쓰고, 없으면 default 사용
    if "안전재고배수" in df.columns:
        df["조정_안전재고배수"] = pd.to_numeric(df["안전재고배수"], errors="coerce").fillna(default_safety)
    else:
        df["조정_안전재고배수"] = default_safety
        
    if "리드타임_일" in df.columns:
        df["조정_리드타임"] = pd.to_numeric(df["리드타임_일"], errors="coerce").fillna(default_lead)
    else:
        df["조정_리드타임"] = default_lead
        
    df["최종확정생산량"] = np.nan

    # 2. 세션에 저장된 사용자 오버라이드 값 덮어쓰기
    overrides = st.session_state["sop_overrides"]
    for idx, row in df.iterrows():
        code = row["상품코드"]
        if code in overrides:
            user_vals = overrides[code]
            if "조정_안전재고배수" in user_vals and user_vals["조정_안전재고배수"] is not None: 
                df.at[idx, "조정_안전재고배수"] = user_vals["조정_안전재고배수"]
            if "조정_리드타임" in user_vals and user_vals["조정_리드타임"] is not None: 
                df.at[idx, "조정_리드타임"] = user_vals["조정_리드타임"]
            if "조정_월평균출고량" in user_vals and user_vals["조정_월평균출고량"] is not None: 
                df.at[idx, "조정_월평균출고량"] = user_vals["조정_월평균출고량"]
            if "최종확정생산량" in user_vals and user_vals["최종확정생산량"] is not None: 
                df.at[idx, "최종확정생산량"] = user_vals["최종확정생산량"]

    # ── 2차 지표 계산 (조정된 값 기반) ──
    df["일평균출고량"] = df["조정_월평균출고량"] / 30
    df["가용재고"] = df["현재고"] + df["입고예정수량"]
    df["현재_사용가능일"] = df.apply(lambda r: safe_divide(r["가용재고"], r["일평균출고량"]), axis=1)
    df["예상소진일"] = df["현재_사용가능일"].apply(lambda v: _calc_expiry(v, today))
    
    df["목표안전재고량"] = df["조정_월평균출고량"] * df["조정_안전재고배수"]
    
    def _calc_order_date(expiry_str, lt):
        if expiry_str in ["출고없음", "∞", "-"]:
            return expiry_str
        try:
            d = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            order_d = d - timedelta(days=int(lt))
            if order_d < today:
                return today.strftime("%Y-%m-%d")
            return order_d.strftime("%Y-%m-%d")
        except:
            return expiry_str
            
    df["발주_필요일정"] = df.apply(lambda r: _calc_order_date(r["예상소진일"], r["조정_리드타임"]), axis=1)
    
    df["필요생산량_시스템"] = df["목표안전재고량"] - (df["현재고"] + df["입고예정수량"]) + (df["일평균출고량"] * df["조정_리드타임"])
    df["필요생산량_시스템"] = df["필요생산량_시스템"].apply(lambda x: x if x > 0 else 0)
    
    # === MOQ 보정 로직 시작 ===
    cat_col = "품목구분" if "품목구분" in df.columns else "구분" if "구분" in df.columns else "상품구분"
    
    if auto_moq and cat_col and "내포입" in df.columns:
        df["내포입_num"] = pd.to_numeric(df["내포입"], errors="coerce").fillna(1)
        df["임시_스틱필요량"] = df["필요생산량_시스템"] * df["내포입_num"]
        
        cat_sums = df.groupby(cat_col)["임시_스틱필요량"].sum()
        
        for cat, total_sticks in cat_sums.items():
            if 0 < total_sticks < global_moq:
                shortfall = global_moq - total_sticks
                cat_df = df[df[cat_col] == cat]
                
                if not cat_df.empty:
                    # 내포입이 가장 크고(우선), 같으면 월평균실적이 큰 것을 '대표 본품'으로 선정
                    main_sku_idx = cat_df.sort_values(["내포입_num", "월평균_실적"], ascending=[False, False]).index[0]
                    main_sku_box = df.at[main_sku_idx, "내포입_num"]
                    
                    added_boxes = shortfall / main_sku_box # 올림은 아래에서 일괄 처리됨
                    df.at[main_sku_idx, "필요생산량_시스템"] += added_boxes
                    
                    old_name = df.at[main_sku_idx, "상품명"]
                    df.at[main_sku_idx, "상품명"] = f"{old_name} (⚠️ MOQ 보정 +{np.ceil(added_boxes):,.0f}박스)"
    # === MOQ 보정 로직 끝 ===
    
    # 확정생산량이 입력되지 않았다면 시스템 산출량을 기본값으로 사용
    df["최종확정생산량"] = df["최종확정생산량"].fillna(df["필요생산량_시스템"])

    # 소수점 올림 처리
    num_cols = ["현재고", "입고예정수량", "월평균_실적", "조정_월평균출고량", "목표안전재고량", "필요생산량_시스템", "최종확정생산량"]
    for c in num_cols:
        df[c] = df[c].apply(lambda x: np.ceil(x) if isinstance(x, (int, float)) and not np.isnan(x) else x)

    # 내림차순 정렬
    df = df.sort_values("필요생산량_시스템", ascending=False).reset_index(drop=True)

    # 에디터 콜백을 위해 정렬된 상품코드를 세션에 기록
    st.session_state["sop_product_codes"] = df["상품코드"].tolist()

    # 표시용 컬럼 분리
    cat_col = "품목구분" if "품목구분" in df.columns else "구분" if "구분" in df.columns else "상품구분"
    display_cols = [
        cat_col, "상품코드", "상품명", 
        "현재고", "입고예정수량", 
        "조정_월평균출고량", "조정_안전재고배수", "조정_리드타임", 
        "예상소진일", "발주_필요일정", 
        "필요생산량_시스템", "최종확정생산량"
    ]
    
    # 상태 아이콘 표시 (위험도 시각화 보조)
    def _status_icon(row):
        val = row["발주_필요일정"]
        if val in ["출고없음", "∞", "-"]:
            return "🟢 여유"
        try:
            order_d = datetime.strptime(val, "%Y-%m-%d").date()
            diff = (order_d - today).days
            if diff <= 7: return "🔴 임박"
            elif diff <= 30: return "🟡 경고"
            else: return "🟢 여유"
        except:
            return "🟢 여유"
            
    df["상태"] = df.apply(_status_icon, axis=1)
    display_cols.insert(0, "상태")
    
    display_df = df[display_cols].copy()
    
    def highlight_urgent(row):
        if row["상태"] == "🔴 임박":
            return ["background-color: #fee2e2; color: #b91c1c"] * len(row)
        return [""] * len(row)
        
    styled_df = display_df.style.apply(highlight_urgent, axis=1)
    
    st.data_editor(
        styled_df,
        key="sop_data_editor",
        on_change=on_editor_change,
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "상태": st.column_config.TextColumn("상태", disabled=True, width="small"),
            cat_col: st.column_config.TextColumn("분류", disabled=True),
            "상품코드": st.column_config.TextColumn("코드", disabled=True),
            "상품명": st.column_config.TextColumn("상품명", disabled=True, width="large"),
            "현재고": st.column_config.NumberColumn("현재고", disabled=True, format="%d"),
            "입고예정수량": st.column_config.NumberColumn("입고예정", disabled=True, format="%d"),
            "조정_월평균출고량": st.column_config.NumberColumn("가정 월출고량 ✏️", format="%d", help="수요에 맞춰 월평균출고량을 수정하세요"),
            "조정_안전재고배수": st.column_config.NumberColumn("안전재고배수 ✏️", format="%.1f", step=0.1, help="제품별 목표 배수를 수정하세요"),
            "조정_리드타임": st.column_config.NumberColumn("리드타임 ✏️", format="%d", step=1, help="제품별 발주 리드타임을 수정하세요"),
            "예상소진일": st.column_config.TextColumn("예상소진일", disabled=True),
            "발주_필요일정": st.column_config.TextColumn("발주 필요일정", disabled=True),
            "필요생산량_시스템": st.column_config.NumberColumn("시스템 산출량", disabled=True, format="%d"),
            "최종확정생산량": st.column_config.NumberColumn("확정 발주량 ✏️", format="%d", help="최종적으로 발주할 수량을 입력하세요"),
        }
    )
    
    # 합계 요약
    total_sys = display_df["필요생산량_시스템"].sum()
    total_confirmed = display_df["최종확정생산량"].sum()
    st.markdown(f"**전체 시뮬레이션 결과: 시스템 권장 {total_sys:,.0f}개 ➔ 회의 확정 발주량 {total_confirmed:,.0f}개**")
    
    csv = display_df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ 확정된 S&OP 발주안 CSV 다운로드",
        data=csv,
        file_name=f"SOP_확정발주안_{today.strftime('%Y%m%d')}.csv",
        mime="text/csv",
        type="primary"
    )

    # ── 품목별 총 생산수량(스틱 단위) 산출 ──
    st.divider()
    st.markdown('<div class="sec-title">🏭 분류별 확정 생산수량(스틱 단위) 산출</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    <strong>💡 안내</strong><br>
    본품 자체가 스틱 단위로 동일하므로, 동일한 카테고리(품목구분)를 공유하는 여러 제품군(내수용/수출용 등)의 확정생산량에 
    <strong>내포입</strong>을 곱하여 <strong>OEM 제조사에 일괄 발주할 스틱 단위 총 생산수량</strong>을 계산합니다.
    </div>
    """, unsafe_allow_html=True)
    
    if cat_col and "내포입" in df.columns:
        df["내포입_num"] = pd.to_numeric(df["내포입"], errors="coerce").fillna(1)
        df["총 확정생산량(스틱 단위)"] = df["최종확정생산량"] * df["내포입_num"]
        
        agg_df = df.groupby(cat_col, as_index=False)["총 확정생산량(스틱 단위)"].sum()
        agg_df = agg_df[agg_df["총 확정생산량(스틱 단위)"] > 0].sort_values("총 확정생산량(스틱 단위)", ascending=False).reset_index(drop=True)
        
        def check_moq(val):
            if val < global_moq:
                return f"⚠️ {global_moq - val:,.0f}포 부족"
            return "✅ 달성"
            
        agg_df["MOQ 상태"] = agg_df["총 확정생산량(스틱 단위)"].apply(check_moq)
        
        if not agg_df.empty:
            agg_styled = agg_df.style.format({"총 확정생산량(스틱 단위)": "{:,.0f}"})
            st.dataframe(agg_styled, use_container_width=True)
        else:
            st.info("통합 발주가 필요한 생산수량이 없습니다.")
    else:
        st.info("마스터 DB에 '내포입' 컬럼이 없어 계산할 수 없습니다.")

