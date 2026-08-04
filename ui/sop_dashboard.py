import streamlit as st
import pandas as pd
from datetime import timedelta
import numpy as np
from data.processor import get_today_kst, filter_shipping_by_date, aggregate_shipping_by_product, compute_metrics, clean_numeric

def render_sop_dashboard():
    st.markdown("## 📢 S&OP 종합 대시보드")
    st.markdown("전체 품목의 재고, 발주 진행 상황, 최근 판매 트렌드 및 예상 소진일을 한눈에 파악합니다.")

    # 필수 데이터 확인
    master_df = st.session_state.get("master_df")
    inventory_df = st.session_state.get("inventory_df")
    shipping_df = st.session_state.get("shipping_df")
    po_df = st.session_state.get("po_df")

    if master_df is None or inventory_df is None or shipping_df is None:
        st.warning("⚠️ 마스터 DB, 현재고, 출고현황 데이터가 필요합니다. [⚙️ 데이터 설정] 메뉴에서 불러와 주세요.")
        return

    today = get_today_kst()

    # --- S&OP 회의 체크리스트 ---
    with st.expander("✅ S&OP 주간 회의 체크리스트 (가이드)", expanded=False):
        st.info("""
**1. 🔥 품절 위험 (긴급 대처)**
- [ ] 품절 임박 상품(Top Alerts)의 **발주 여부 및 입고 예상일**이 정확히 파악되었는가?
- [ ] 생산 지연 시 항공 운송 등 긴급 배송 전환이 필요한 품목은 없는가?
- [ ] 품절 예상 기간 동안 **광고 예산 축소 또는 프로모션 중단** 조치가 유관 부서에 전달되었는가?

**2. 🧊 과재고 경고 (재고 건전성)**
- [ ] 과재고 품목의 원인(판매 부진, 과다 발주 등)이 파악되었는가? 유통기한(EXP) 압박은 없는가?
- [ ] 재고 소진을 위한 **할인 행사, 기획세트(번들링), 사은품 증정** 등의 판촉 계획이 수립되었는가?

**3. 📦 발주 및 공급망 현황**
- [ ] 현재 진행 중인 발주(PO) 건 중 **수량 조율, 디자인 컨펌, 부자재 수급 지연** 등 특이사항(메모)이 있는 건들의 해결 방안은 무엇인가?
- [ ] 신제품 런칭 또는 리뉴얼 상품의 입고 일정이 마케팅 타임라인과 일치하는가?

**4. 📈 판매 트렌드 및 향후 수요 예측**
- [ ] 전월 대비 판매 트렌드가 **급상승(🔺)한 품목**에 대한 추가 발주(안전재고 상향)가 필요한가?
- [ ] 향후 1~2개월 내 신규 채널 입점이나 대규모 기획전(올영세일, 명절 등)에 대비한 별도의 재고 할당이 반영되었는가?
        """)
        
    st.divider()

    # --- 카테고리 필터 ---
    st.markdown("##### 📌 분석 대상 구분 필터")
    categories = sorted(master_df["구분"].dropna().unique().tolist())
    selected_cats = []
    
    if categories:
        num_cols = min(len(categories), 6)
        if num_cols == 0: num_cols = 1
        cols = st.columns(num_cols)
        for i, cat in enumerate(categories):
            default_val = (cat == "상품")
            with cols[i % num_cols]:
                if st.checkbox(cat, value=default_val, key=f"sop_cat_chk_{cat}"):
                    selected_cats.append(cat)

    with st.spinner("S&OP 지표 계산 중..."):
        # 1. 필터 적용된 더미 마스터 생성
        master_slim = master_df[["구분", "품목구분", "상품코드", "상품명"]].copy()
        master_slim = master_slim[master_slim["구분"].isin(selected_cats)]

        # 2. 전체 채널 합산 현재고 생성
        inv_agg = inventory_df.groupby("상품코드", as_index=False)["현재고"].sum()
        master_slim = master_slim.drop_duplicates(subset=["상품코드"])

        # 채널 구분을 없애기 위해 출고 데이터에서 채널 컬럼 제거
        shipping_slim = shipping_df.copy()
        if "채널" in shipping_slim.columns:
            shipping_slim = shipping_slim.drop(columns=["채널"])

        # 3. compute_metrics 활용 (통합)
        metrics_df = compute_metrics(master_slim, inv_agg, shipping_slim)

        # 4. 최근 판매 트렌드 계산 (최근 30일 vs 이전 30일)
        last_30d_start = today - timedelta(days=30)
        prev_30d_start = today - timedelta(days=60)

        ship_last_30 = filter_shipping_by_date(shipping_slim, last_30d_start, today)
        ship_prev_30 = filter_shipping_by_date(shipping_slim, prev_30d_start, last_30d_start - timedelta(days=1))

        last_30_agg = aggregate_shipping_by_product(ship_last_30).rename(columns={"총출고수량": "최근30일_출고량"})
        prev_30_agg = aggregate_shipping_by_product(ship_prev_30).rename(columns={"총출고수량": "이전30일_출고량"})

        # 지표 병합
        metrics_df = metrics_df.merge(last_30_agg[["상품코드", "최근30일_출고량"]], on="상품코드", how="left")
        metrics_df = metrics_df.merge(prev_30_agg[["상품코드", "이전30일_출고량"]], on="상품코드", how="left")
        metrics_df["최근30일_출고량"] = metrics_df["최근30일_출고량"].fillna(0)
        metrics_df["이전30일_출고량"] = metrics_df["이전30일_출고량"].fillna(0)

        # 트렌드 증감률 계산
        def calc_trend(row):
            curr = row["최근30일_출고량"]
            prev = row["이전30일_출고량"]
            if prev == 0 and curr > 0:
                return "100% 🔺"
            elif prev == 0 and curr == 0:
                return "-"
            else:
                pct = ((curr - prev) / prev) * 100
                if pct > 0:
                    return f"{pct:.1f}% 🔺"
                elif pct < 0:
                    return f"{abs(pct):.1f}% 🔻"
                else:
                    return "0.0%"

        metrics_df["30일_판매트렌드"] = metrics_df.apply(calc_trend, axis=1)

        # 5. PO 리스트업 및 가상 재고(입고 대기 상태) 산출
        pending_pos = pd.DataFrame()
        po_agg = pd.DataFrame(columns=["상품코드", "입고예정수량"])
        
        if po_df is not None and not po_df.empty:
            # "8. 생산, 입고완료" 상태가 아닌 것들을 필터링 ("완료"만 체크하면 디자인검토완료가 누락됨)
            pending_pos = po_df[~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False)].copy()
            
            if not pending_pos.empty:
                # 선택된 카테고리의 상품만 남김
                if not master_slim.empty:
                    pending_pos = pending_pos[pending_pos["상품코드"].isin(master_slim["상품코드"])]
                
                po_agg = pending_pos.groupby("상품코드", as_index=False)["발주수량"].sum().rename(columns={"발주수량": "입고예정수량"})

        # 6. 가상 재고 및 입고반영 예상소진일수 계산
        metrics_df = metrics_df.merge(po_agg, on="상품코드", how="left")
        metrics_df["입고예정수량"] = metrics_df["입고예정수량"].fillna(0)
        metrics_df["가상재고"] = metrics_df["현재고"] + metrics_df["입고예정수량"]
        
        def calc_virtual_doi(row):
            rate = row["3개월 일평균 출고량"]
            if pd.isna(rate) or rate == 0:
                return 9999.0
            return row["가상재고"] / rate
            
        metrics_df["가상소진일수"] = metrics_df.apply(calc_virtual_doi, axis=1)

    st.divider()

    # --- TOP ALERTS 구역 ---
    st.markdown("### 🚨 긴급 알림 (Top Alerts)")

    # 품절 위험 (입고반영 예상 소진일이 리드타임 45일 미만인 경우)
    risk_df = metrics_df[(metrics_df["가상소진일수"] >= 0) & (metrics_df["가상소진일수"] < 45)].sort_values("가상소진일수")
    
    # 과재고 경고 (입고반영 예상 소진일이 리드타임 3배수 135일 이상이고 총 재고가 0 초과인 경우)
    overstock_df = metrics_df[(metrics_df["가상소진일수"] >= 135) & (metrics_df["가상재고"] > 0)].sort_values("가상소진일수", ascending=False)

    col1, col2 = st.columns(2)
    with col1:
        st.error(f"**🔥 품절 위험 (입고반영 예상 소진 45일 미만)** : {len(risk_df)}건")
        if not risk_df.empty:
            show_risk = risk_df[["상품명", "현재고", "입고예정수량", "가상소진일수"]].copy()
            show_risk["현재고"] = show_risk["현재고"].apply(lambda x: f"{float(x):,.0f}" if pd.notna(x) and str(x).replace('.','',1).isdigit() else str(x))
            show_risk["입고예정수량"] = show_risk["입고예정수량"].apply(lambda x: f"{float(x):,.0f}" if pd.notna(x) and str(x).replace('.','',1).isdigit() else str(x))
            
            def format_doi_risk(x):
                try: return f"{float(x):,.1f}"
                except: return str(x)
            show_risk["가상소진일수"] = show_risk["가상소진일수"].apply(format_doi_risk)
            
            show_risk.columns = ["상품명", "현재고(개)", "입고예정(개)", "소진예상(일)"]
            st.dataframe(show_risk, hide_index=True, use_container_width=True, height=250)
        else:
            st.success("품절 위험 품목이 없습니다.")

    with col2:
        st.warning(f"**🧊 과재고 경고 (입고반영 예상 소진 135일 이상)** : {len(overstock_df)}건")
        if not overstock_df.empty:
            show_over = overstock_df[["상품명", "가상재고", "가상소진일수"]].copy()
            show_over["가상재고"] = show_over["가상재고"].apply(lambda x: f"{float(x):,.0f}" if pd.notna(x) and str(x).replace('.','',1).isdigit() else str(x))
            
            def format_doi_over(x):
                try: return "출고량 없음" if float(x) >= 9999 else f"{float(x):,.1f}"
                except: return str(x)
            show_over["가상소진일수"] = show_over["가상소진일수"].apply(format_doi_over)
            
            show_over.columns = ["상품명", "총재고(가상)", "소진예상(일)"]
            st.dataframe(show_over, hide_index=True, use_container_width=True, height=250)
        else:
            st.success("과재고 품목이 없습니다.")

    st.divider()

    # --- 발주 현황 구역 ---
    st.markdown("### 📦 발주 및 입고 진행 현황")
    if not pending_pos.empty:
        # 보여줄 컬럼 선택 (비고 포함)
        po_cols = ["납기예정일", "외주처", "상품명", "발주수량", "입고상태"]
        if "비고" in pending_pos.columns:
            po_cols.append("비고")
            
        po_display = pending_pos[po_cols].copy()
        po_display = po_display.sort_values("납기예정일", na_position="last")
        
        # DataFrame 렌더링
        col_config_po = {
            "납기예정일": st.column_config.DateColumn("납기예정일", format="YYYY-MM-DD"),
            "외주처": st.column_config.TextColumn("외주처/발주처"),
            "상품명": st.column_config.TextColumn("상품명"),
            "발주수량": st.column_config.NumberColumn("발주수량(개)"),  # format 지정 제거하여 기본 콤마 적용
            "입고상태": st.column_config.TextColumn("진행상태"),
        }
        if "비고" in po_display.columns:
            col_config_po["비고"] = st.column_config.TextColumn("특이사항 (메모)")

        # 수량에 명시적 콤마 포맷팅 적용 (정렬보다 표시가 더 중요한 표)
        def format_po_qty(x):
            try: return f"{float(x):,.0f}"
            except: return str(x)
        po_display["발주수량"] = po_display["발주수량"].apply(format_po_qty)
        col_config_po["발주수량"] = st.column_config.TextColumn("발주수량(개)")

        st.dataframe(
            po_display,
            column_config=col_config_po,
            hide_index=True,
            use_container_width=True,
            height=250
        )
    else:
        st.info("현재 대기 중인 발주(PO) 내역이 없습니다.")

    st.divider()

    # --- 종합 현황판 ---
    col_title, col_opt = st.columns([4, 1])
    with col_title:
        st.markdown("### 📊 전체 품목 통합 현황판")
    with col_opt:
        hide_zero = st.checkbox("🚫 현재고 0 숨기기", key="sop_hide_zero", value=True)
        
    if hide_zero:
        metrics_df = metrics_df[metrics_df["현재고"] > 0].copy()
    
    # 렌더링용 컬럼 구성
    display_cols = [
        "구분", "상품명", "현재고", "최근30일_출고량", "30일_판매트렌드", 
        "3개월 일평균 출고량", "사용가능(일)", "예상소진일"
    ]
    
    # 숫자 포맷팅용 딕셔너리
    col_config = {
        "구분": st.column_config.TextColumn("구분", width="small"),
        "상품명": st.column_config.TextColumn("상품명", width="medium"),
        "현재고": st.column_config.NumberColumn("현재고 (전체)"),  # format 제거 시 Streamlit 기본 콤마(thousands) 적용
        "최근30일_출고량": st.column_config.NumberColumn("최근 30일 출고"),
        "30일_판매트렌드": st.column_config.TextColumn("전월대비 추세"),
        "3개월 일평균 출고량": st.column_config.NumberColumn("일평균 출고속도 (Run Rate)", format="%.1f"),
        "사용가능(일)": st.column_config.NumberColumn("소진예상일수 (DOI)", format="%.1f"),
        "예상소진일": st.column_config.TextColumn("소진예상일자 (날짜)"),
    }

    # 정렬: 품절 임박 상품이 최상단에 오도록 '소진일수' 오름차순 정렬 (DOI 기준)
    # 문자열 '출고없음'을 NaN으로 처리한 뒤 최하단(last)에 배치
    metrics_df["소진일수_숫자"] = pd.to_numeric(metrics_df["사용가능(일)"], errors="coerce")
    
    board_df = metrics_df.sort_values(
        by=["소진일수_숫자", "구분", "상품명"], 
        ascending=[True, True, True], 
        na_position="last"
    ).reset_index(drop=True)
    
    # 판다스 Styler를 이용해 강력한 포맷팅(콤마 등) 유지
    def format_num_0(x):
        try: return f"{float(x):,.0f}"
        except: return str(x)
        
    def format_num_1(x):
        try: return f"{float(x):,.1f}"
        except: return str(x)

    styled_board = board_df[display_cols].style.format({
        "현재고": format_num_0,
        "최근30일_출고량": format_num_0,
        "3개월 일평균 출고량": format_num_1,
        "사용가능(일)": format_num_1
    })

    st.dataframe(
        styled_board,
        column_config=col_config,
        hide_index=True,
        use_container_width=True,
        height=600
    )



