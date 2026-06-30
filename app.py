"""
app.py  ─  재고·출고 대시보드 진입점
============================================================
변경 이력
  v2  실제 xls 파일 컬럼 구조 반영 + Google Sheets 편집 URL 자동 파싱
      xls → LibreOffice 변환 파이프라인 내장 (xlrd 불필요)
      Supabase 통합 & UI 개편 (S&OP 시뮬레이션 추가)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

import re

from data.processor import (
    build_gsheet_csv_url,
    load_master_from_gsheet,
    parse_inventory_file,
    parse_shipping_file,
    parse_ownist_shipping_file,
    parse_daily_shipping_file,
    parse_shinsegae_file,
    load_code_mapping_from_gsheet,
    translate_product_codes,
    filter_shipping_by_date,
    aggregate_shipping_daily,
    compute_metrics,
    get_today_kst,
)
from ui.components import (
    setup_page,
    render_header,
    render_kpi_row,
    render_metrics_table,
    render_shipping_table,
    render_error,
    render_success,
)

from data.supabase_client import (
    fetch_shipping_data,
    upsert_shipping_data,
    upsert_ownist_shipping,
    fetch_inventory_data,
    upsert_inventory_data,
)
from ui.sop_simulation import render_sop_simulation


# ════════════════════════════════════════════════
# 추가 CSS (dashboard.py UI 이식용)
# ════════════════════════════════════════════════
DASHBOARD_CSS = """
<style>
/* 메인 컨테이너 상단 여백 제거 */
[data-testid="block-container"] {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
}
[data-testid="stHeader"] {
    display: none !important;
}

/* 필터 영역 고정 (Sticky) */
div[data-testid="stVerticalBlock"] > div:has(.sticky-header) {
    position: -webkit-sticky;
    position: sticky;
    top: 0;
    z-index: 999;
    background-color: #f8fafc !important;
    padding-bottom: 5px !important;
    border-bottom: 1px solid #e2e8f0 !important;
}

/* 사이드바 라디오 버튼 메뉴 스타일 */
.stRadio > div { gap: 0px !important; }
.stRadio label {
    background-color: transparent !important;
    border-radius: 0px !important;
    padding: 12px 16px !important;
    transition: all 0.2s !important;
    border-bottom: 1px solid #f1f3f5 !important;
    margin: 0 !important;
    cursor: pointer !important;
}
.stRadio label:hover {
    background-color: #f1f5f9 !important;
}
.stRadio [data-testid="stWidgetLabel"] { display: none !important; }
</style>
"""


# ════════════════════════════════════════════════
# 페이지 설정
# ════════════════════════════════════════════════
setup_page()
st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

# ════════════════════════════════════════════════
# 세션 상태 초기화
# ════════════════════════════════════════════════
for _k, _v in {
    "master_df": None,
    "mapping_df": None,
    "inventory_df": None,
    "shipping_df": None, # 이제 Supabase에서 조회한 전체 데이터 담음
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ════════════════════════════════════════════════
# 자동 로딩 로직 (마스터 DB 및 현재고 DB)
# ════════════════════════════════════════════════
DEFAULT_GSHEET_URL = "https://docs.google.com/spreadsheets/d/1NxEiNIh0UK0XHfDiqntcG4tdJai_emkyEz-rTwfr4q4/edit?gid=1703000362#gid=1703000362"

if st.session_state["master_df"] is None:
    try:
        st.session_state["master_df"] = load_master_from_gsheet(DEFAULT_GSHEET_URL)
        st.session_state["mapping_df"] = load_code_mapping_from_gsheet(DEFAULT_GSHEET_URL)
    except Exception as e:
        st.error(f"마스터 DB 자동 로드 실패: {e}")

if st.session_state["inventory_df"] is None:
    try:
        st.session_state["inventory_df"] = fetch_inventory_data()
    except Exception as e:
        pass



today = get_today_kst()

# ════════════════════════════════════════════════
# 사이드바 메뉴 및 설정
# ════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 📌 메뉴")
    # 탭 대신 메뉴 방식으로 구현
    menu = st.radio(
        "메뉴 선택",
        ["📊 재고 대시보드", "🚚 일자별 출고현황", "🔮 S&OP 시뮬레이션", "⚙️ 데이터 설정"],
        label_visibility="collapsed"
    )
    
    st.divider()

    if menu != "⚙️ 데이터 설정":
        st.markdown(
            '<div style="font-size:.68rem;color:#4b5563;text-align:center;line-height:1.5">'
            '데이터 변경/업데이트는<br><b>[⚙️ 데이터 설정]</b> 메뉴를 이용하세요.</div>',
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════
# 메인 영역 - 헤더
# ════════════════════════════════════════════════
if menu != "⚙️ 데이터 설정":
    render_header()


# 준비 상태 체크
master_ok    = st.session_state["master_df"] is not None
inventory_ok = st.session_state["inventory_df"] is not None

# ════════════════════════════════════════════════
# 메뉴: ⚙️ 데이터 설정
# ════════════════════════════════════════════════
if menu == "⚙️ 데이터 설정":
    st.markdown("## ⚙️ 데이터 설정 및 업데이트")
    st.markdown("이곳에서 마스터 DB 갱신, 현재고 업로드, 일자별 출고현황(Supabase 전송)을 수행할 수 있습니다.")
    
    # 마스터 DB는 채널과 무관하게 공통 적용
    st.markdown("### ① 공통 마스터 DB (Google Sheets)")
    gsheet_url = st.text_input(
        "Google Sheets URL (수동 갱신용)",
        value=DEFAULT_GSHEET_URL,
        placeholder="https://docs.google.com/spreadsheets/d/...",
        help="편집 URL 또는 export CSV URL 모두 가능합니다. 시트명 'DB'가 기준입니다.",
    )
    if st.button("📥 마스터 DB 새로고침", use_container_width=False):
        if not gsheet_url.strip():
            render_error("Google Sheets URL을 입력해 주세요.")
        else:
            with st.spinner("마스터 DB 수동 로드 중..."):
                try:
                    import data.processor
                    data.processor.load_master_from_gsheet.clear() # 캐시 초기화
                    data.processor.load_code_mapping_from_gsheet.clear() # 매핑 시트 캐시 초기화
                    st.session_state["master_df"] = load_master_from_gsheet(gsheet_url.strip())
                    st.session_state["mapping_df"] = load_code_mapping_from_gsheet(gsheet_url.strip())
                    render_success(f"마스터 DB 새로고침 완료 — {len(st.session_state['master_df'])}개 상품")
                except Exception as e:
                    render_error(f"마스터 DB 로드 실패: {e}")

    st.divider()
    st.markdown("### ② 채널별 데이터 업로드 (Supabase 연동)")
    
    # 탭으로 채널 분리
    upload_tabs = st.tabs(["CK로지스 (WMS)", "신세계면세점", "미국 (Amazon)"])
    
    with upload_tabs[0]:
        st.markdown("**[CK로지스] 현재고 및 일자별 출고현황 업로드**")
        c1, c2 = st.columns(2)
        
        with c1:
            st.markdown("#### 현재고 파일")
            inventory_file = st.file_uploader(
                "현재고 (.xls / .xlsx)",
                type=["xls", "xlsx"],
                key="inv_upload_domestic",
                help="예: 현재고_YYYYMMDD.xls (적치존 기준)",
            )
            if inventory_file:
                if st.button("🚀 현재고 Supabase 전송", key="btn_inv_dom", use_container_width=True):
                    with st.spinner("현재고 파일 처리 및 전송 중..."):
                        try:
                            new_inv_df = parse_inventory_file(inventory_file)
                            upsert_count = upsert_inventory_data(new_inv_df, channel="CK로지스")
                            st.session_state["inventory_df"] = fetch_inventory_data()
                            render_success(f"[CK로지스] 현재고 업데이트 완료 — {upsert_count}개 상품")
                        except Exception as e:
                            render_error(f"현재고 파일 오류: {e}")

        with c2:
            st.markdown("#### 출고완료 내역")
            shipping_file = st.file_uploader(
                "일자별 출고현황 (.xls, .xlsx)",
                type=["xls", "xlsx"],
                key="ship_upload_domestic",
                help="일자별 출고현황_YYYYMMDD.xls 파일을 올려주세요.",
            )
            if shipping_file:
                if st.button("🚀 출고 데이터 Supabase 전송", key="btn_ship_dom", use_container_width=True):
                    with st.spinner("파일 처리 및 전송 중..."):
                        try:
                            new_shipping_df = parse_daily_shipping_file(shipping_file)
                            upsert_count, filtered_df = upsert_ownist_shipping(new_shipping_df, channel="CK로지스")
                            st.session_state["shipping_df"] = None  # 캐시 초기화
                            
                            min_date = filtered_df['출고일자'].min() if not filtered_df.empty else "-"
                            max_date = filtered_df['출고일자'].max() if not filtered_df.empty else "-"
                            
                            render_success(f"[CK로지스] 출고 업데이트 완료! ({upsert_count}건 반영, {min_date}~{max_date})")
                        except Exception as e:
                            render_error(f"출고현황 처리 오류: {e}")

    with upload_tabs[1]:
        st.markdown("**[신세계면세점] 기간 누적 마감 엑셀 업로드**")
        st.info(
            "💡 **[중요]** 엑셀 파일의 실제 **조회 기간(시작일~종료일)**을 정확히 선택해 주세요.\n\n"
            "시스템이 선택하신 기간 내의 과거 업로드 내역을 조회하여, **'순수하게 추가로 발생한 출고량(Delta)'**만 추출하여 종료일 날짜로 저장합니다."
        )
        
        # 시작일 - 종료일 범위 선택 UI (최근 7일 기본값)
        today = get_today_kst()
        default_start = today - timedelta(days=7)
        ssg_date_range = st.date_input("엑셀 조회 기간 (시작일 - 종료일)", value=(default_start, today))
        
        ssg_file = st.file_uploader(
            "신세계면세점 마감 엑셀 (.xls / .xlsx)",
            type=["xls", "xlsx"],
            key="ssg_upload",
            help="선택한 기간 동안의 누적 판매수량 및 기말재고가 포함된 파일을 업로드하세요.",
        )
        
        if ssg_file:
            if st.button("🚀 신세계면세점 데이터 전송", key="btn_ssg", use_container_width=True):
                # 기간 선택 값 확인
                if isinstance(ssg_date_range, tuple) and len(ssg_date_range) == 2:
                    start_date, end_date = ssg_date_range
                elif isinstance(ssg_date_range, tuple) and len(ssg_date_range) == 1:
                    start_date = end_date = ssg_date_range[0]
                else:
                    start_date = end_date = ssg_date_range

                with st.spinner("파일 역산 처리 및 Supabase 전송 중..."):
                    try:
                        # end_date를 기준 일자로 사용하되, start_date 정보도 함께 전달
                        ship_df, inv_df = parse_shinsegae_file(ssg_file, end_date)
                        
                        # [코드 매핑 적용] 신세계면세점 상품코드를 표준 마스터 DB 코드로 변환
                        mapping_df = st.session_state.get("mapping_df")
                        if mapping_df is not None and not mapping_df.empty:
                            ship_df = translate_product_codes(ship_df, "신세계면세점", mapping_df)
                            inv_df = translate_product_codes(inv_df, "신세계면세점", mapping_df)
                        
                        # Dataframe에 start_date 메타데이터 심기 (upsert_ownist_shipping에서 활용)
                        ship_df["조회시작일"] = start_date
                        
                        # 1. 재고 데이터 업데이트
                        inv_count = upsert_inventory_data(inv_df, channel="신세계면세점")
                        
                        # 2. 출고 데이터 업데이트 (누적 데이터 차감 로직 적용)
                        ship_count, filtered_df = upsert_ownist_shipping(
                            ship_df, channel="신세계면세점", is_cumulative=True
                        )
                        
                        # 세션 초기화 및 재조회
                        st.session_state["inventory_df"] = fetch_inventory_data()
                        st.session_state["shipping_df"] = None
                        
                        render_success(f"[신세계면세점] 업데이트 완료! (재고 {inv_count}건, 순수 일일 출고 {ship_count}건 반영)")
                        
                        with st.expander("📋 신세계 일일 순수 출고량(Delta) 미리보기"):
                            st.dataframe(filtered_df.head(10), use_container_width=True)
                            
                    except Exception as e:
                        render_error(f"신세계면세점 데이터 처리 오류: {e}")
        
    with upload_tabs[2]:
        st.info("🚧 미국(Amazon 등) 전용 업로드 파싱 로직 및 UI는 [Phase 1] 진행에 따라 곧 추가될 예정입니다.")

    st.divider()
    
    st.markdown("#### ✅ 데이터 준비 상태")
    st.write("- **마스터 DB**: " + ("🟢 로드됨" if master_ok else "🔴 필요"))
    st.write("- **현재고 파일**: " + ("🟢 로드됨" if inventory_ok else "🔴 필요"))
    
    # 여기서 Supabase 데이터 존재 여부 확인 (최초 로드)
    if st.session_state["shipping_df"] is None:
        with st.spinner("Supabase에서 출고 데이터를 확인 중..."):
            try:
                st.session_state["shipping_df"] = fetch_shipping_data()
            except Exception as e:
                pass
                
    ship_cnt = len(st.session_state.get("shipping_df", [])) if st.session_state.get("shipping_df") is not None else 0
    st.write(f"- **Supabase 출고 데이터**: " + (f"🟢 누적 {ship_cnt:,}건" if ship_cnt > 0 else "🔴 데이터 없음"))
    
    st.stop()


# ════════════════════════════════════════════════
# 필수 데이터 확인
# ════════════════════════════════════════════════
if not master_ok or not inventory_ok:
    st.warning("⚠️ 마스터 DB와 현재고 파일을 먼저 [⚙️ 데이터 설정] 메뉴에서 불러와 주세요.")
    st.stop()
    
# Shipping Data Lazy Loading from Supabase
if st.session_state["shipping_df"] is None:
    with st.spinner("Supabase에서 출고 데이터를 불러오는 중..."):
        try:
            st.session_state["shipping_df"] = fetch_shipping_data()
        except Exception as e:
            render_error(f"Supabase 출고 데이터 조회 실패: {e}")
            st.stop()

if st.session_state["shipping_df"].empty:
    st.warning("⚠️ Supabase에 누적된 출고 데이터가 없습니다. [⚙️ 데이터 설정]에서 출고현황 파일을 업로드해 주세요.")


# ════════════════════════════════════════════════
# 공통 상단 필터 (Sticky)
# ════════════════════════════════════════════════
st.markdown('<div class="sticky-header"></div>', unsafe_allow_html=True)
with st.container():
    # 필터 영역 디자인 (5열로 확장)
    fc1, fc2, fc_ch, fc3, fc4 = st.columns([1, 1, 1, 1, 1])
    
    # 1) 구분 필터
    구분_opts = ["전체"] + sorted(st.session_state["master_df"]["구분"].dropna().unique().tolist())
    sel_구분 = fc1.selectbox("구분", 구분_opts, key="fil_구분_공통")
    
    # 2) 품목구분 필터
    품목_opts = ["전체"] + sorted(st.session_state["master_df"]["품목구분"].dropna().unique().tolist())
    sel_품목 = fc2.selectbox("품목구분", 품목_opts, key="fil_품목_공통")

    # 3) 채널 필터
    inv_ch = st.session_state["inventory_df"]["채널"].unique().tolist() if not st.session_state["inventory_df"].empty else []
    ship_ch = st.session_state["shipping_df"]["채널"].unique().tolist() if not st.session_state["shipping_df"].empty else []
    channel_opts = ["전체"] + sorted(list(set(inv_ch + ship_ch)))
    sel_channel = fc_ch.selectbox("채널", channel_opts, key="fil_채널_공통")
    
    # 4) 날짜 필터 (출고현황 등에 영향)
    start_date = fc3.date_input("출고 시작일", value=today - timedelta(days=30))
    end_date = fc4.date_input("출고 종료일", value=today)
    
    st.divider()


# ════════════════════════════════════════════════
# 데이터 필터링 적용
# ════════════════════════════════════════════════
# 1. 마스터 DB 필터링
filtered_master = st.session_state["master_df"].copy()
if sel_구분 != "전체":
    filtered_master = filtered_master[filtered_master["구분"] == sel_구분]
if sel_품목 != "전체":
    filtered_master = filtered_master[filtered_master["품목구분"] == sel_품목]

# 2. 인벤토리/출고 데이터 채널 필터링
filtered_inv = st.session_state["inventory_df"].copy()
filtered_ship = st.session_state["shipping_df"].copy()

if sel_channel != "전체":
    if "채널" in filtered_inv.columns:
        filtered_inv = filtered_inv[filtered_inv["채널"] == sel_channel]
    if "채널" in filtered_ship.columns:
        filtered_ship = filtered_ship[filtered_ship["채널"] == sel_channel]

# ════════════════════════════════════════════════
# 메뉴: 📊 재고 대시보드
# ════════════════════════════════════════════════
if menu == "📊 재고 대시보드":
    try:
        metrics_df = compute_metrics(
            filtered_master,
            filtered_inv,
            filtered_ship,
        )

        render_kpi_row(metrics_df, today)

        # 보기 옵션 체크박스들
        col_chk1, col_chk2 = st.columns(2)
        with col_chk1:
            only_danger = st.checkbox("⚠️ 안전재고 미달만 보기", key="fil_danger")
        with col_chk2:
            hide_zero = st.checkbox("🚫 현재고 0 숨기기", key="fil_hide_zero", value=True)

        view = metrics_df.copy()
        if only_danger:
            view = view[
                view["안전재고 미만"].apply(lambda v: isinstance(v, (int, float)) and v < 0)
            ]
        if hide_zero:
            view = view[view["현재고"] > 0]

        render_metrics_table(view)

    except Exception as e:
        render_error(f"지표 산출 오류: {e}")
        st.exception(e)


# ════════════════════════════════════════════════
# 메뉴: 🚚 일자별 출고현황
# ════════════════════════════════════════════════
elif menu == "🚚 일자별 출고현황":
    try:
        filtered_shipping = filter_shipping_by_date(
            st.session_state["shipping_df"], start_date, end_date
        )
        daily = aggregate_shipping_daily(filtered_shipping)

        # 필터링된 마스터 데이터에 존재하는 상품코드만 남기기 (상품구분 필터 적용)
        daily = daily[daily["상품코드"].isin(filtered_master["상품코드"])]

        # 상품명 조인
        daily = daily.merge(
            filtered_master[["상품코드", "상품명"]],
            on="상품코드", how="left",
        )

        render_shipping_table(daily, start_date, end_date)

    except Exception as e:
        render_error(f"출고현황 조회 오류: {e}")
        st.exception(e)


# ════════════════════════════════════════════════
# 메뉴: 🔮 S&OP 시뮬레이션
# ════════════════════════════════════════════════
elif menu == "🔮 S&OP 시뮬레이션":
    try:
        render_sop_simulation(
            filtered_master,
            st.session_state["inventory_df"],
            st.session_state["shipping_df"],
            today
        )
    except Exception as e:
        render_error(f"S&OP 시뮬레이션 오류: {e}")
        st.exception(e)
