"""
app.py  ─  재고·출고 대시보드 진입점
============================================================
변경 이력
  v2  실제 xls 파일 컬럼 구조 반영 + Google Sheets 편집 URL 자동 파싱
      xls → LibreOffice 변환 파이프라인 내장 (xlrd 불필요)
      Supabase 통합 & UI 개편 (S&OP 시뮬레이션 추가)
"""

# Streamlit Cache Invalidation Trigger - 2
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import sys
import importlib

if 'data.processor' in sys.modules:
    importlib.reload(sys.modules['data.processor'])
if 'data.supabase_client' in sys.modules:
    importlib.reload(sys.modules['data.supabase_client'])
if 'ui.components' in sys.modules:
    importlib.reload(sys.modules['ui.components'])
if 'ui.sop_simulation' in sys.modules:
    importlib.reload(sys.modules['ui.sop_simulation'])
if 'ui.po_calendar' in sys.modules:
    importlib.reload(sys.modules['ui.po_calendar'])
if 'ui.projected_inventory' in sys.modules:
    importlib.reload(sys.modules['ui.projected_inventory'])
if 'ui.transfer_manager' in sys.modules:
    importlib.reload(sys.modules['ui.transfer_manager'])

import re

from data.processor import (
    build_gsheet_csv_url,
    load_master_from_gsheet,
    parse_inventory_file,
    parse_shipping_file,
    parse_ownist_shipping_file,
    parse_daily_shipping_file,
    parse_multi_channel_file,
    load_code_mapping_from_gsheet,
    load_po_from_gsheet,
    translate_product_codes,
    filter_shipping_by_date,
    aggregate_shipping_daily,
    aggregate_shipping_monthly,
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
    "po_df": None, # 발주 데이터 담음
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ════════════════════════════════════════════════
# 자동 로딩 로직 (마스터 DB 및 현재고 DB)
# ════════════════════════════════════════════════
DEFAULT_GSHEET_URL = "https://docs.google.com/spreadsheets/d/1NxEiNIh0UK0XHfDiqntcG4tdJai_emkyEz-rTwfr4q4/edit?gid=1703000362#gid=1703000362"
DEFAULT_MAPPING_URL = "https://docs.google.com/spreadsheets/d/1NxEiNIh0UK0XHfDiqntcG4tdJai_emkyEz-rTwfr4q4/edit?gid=275066073#gid=275066073"
DEFAULT_PO_URL = "https://docs.google.com/spreadsheets/d/1NxEiNIh0UK0XHfDiqntcG4tdJai_emkyEz-rTwfr4q4/edit?gid=1362766974#gid=1362766974"

if st.session_state.get("po_url") is None:
    st.session_state["po_url"] = DEFAULT_PO_URL
if st.session_state.get("transfer_url") is None:
    st.session_state["transfer_url"] = ""

if st.session_state["master_df"] is None:
    try:
        st.session_state["master_df"] = load_master_from_gsheet(DEFAULT_GSHEET_URL)
        st.session_state["mapping_df"] = load_code_mapping_from_gsheet(DEFAULT_MAPPING_URL)
        
        if st.session_state["po_url"]:
            st.session_state["po_df"] = load_po_from_gsheet(st.session_state["po_url"], "발주")
    except Exception as e:
        st.error(f"마스터 DB 자동 로드 실패: {e}")

if st.session_state.get("transfer_df") is None:
    try:
        from data.supabase_client import fetch_transfers
        st.session_state["transfer_df"] = fetch_transfers()
    except Exception as e:
        pass

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
        ["📊 재고 대시보드", "📊 채널별 재고 대시보드", "🚚 기간별 출고현황", "🔮 S&OP 시뮬레이션", "📦 발주 및 입고현황", "🚢 선적 및 이동 관리", "🌐 다단계 예상재고", "⚙️ 데이터 설정"],
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
        "마스터 DB URL",
        value=DEFAULT_GSHEET_URL,
        placeholder="https://docs.google.com/spreadsheets/d/...",
        help="편집 URL 또는 export CSV URL 모두 가능합니다. 시트명 'DB'가 기준입니다.",
    )
    
    st.markdown("### 📦 발주 DB (Google Sheets)")
    
    po_gsheet_url = st.text_input(
        "발주 DB URL",
        value=st.session_state.get("po_url", DEFAULT_PO_URL),
        placeholder="발주 시트 URL (gid 포함)",
    )
    
    if st.button("📥 구글 시트 데이터 새로고침 (마스터 & 발주)", use_container_width=False):
        if not gsheet_url.strip():
            render_error("마스터 DB URL을 입력해 주세요.")
        else:
            with st.spinner("구글 시트 데이터 로드 중..."):
                try:
                    import data.processor
                    data.processor.load_master_from_gsheet.clear() # 캐시 초기화
                    data.processor.load_code_mapping_from_gsheet.clear() # 매핑 시트 캐시 초기화
                    data.processor.load_po_from_gsheet.clear() # 발주 시트 캐시 초기화
                    if hasattr(data.processor, 'load_transfer_from_gsheet'):
                        data.processor.load_transfer_from_gsheet.clear() # 선적 시트 캐시 초기화
                    
                    st.session_state["master_df"] = load_master_from_gsheet(gsheet_url.strip())
                    st.session_state["mapping_df"] = load_code_mapping_from_gsheet(DEFAULT_MAPPING_URL)
                    
                    if po_gsheet_url.strip():
                        st.session_state["po_url"] = po_gsheet_url.strip()
                        st.session_state["po_df"] = load_po_from_gsheet(po_gsheet_url.strip(), "발주")
                    else:
                        st.session_state["po_df"] = pd.DataFrame()
                        
                    from data.supabase_client import fetch_transfers
                    st.session_state["transfer_df"] = fetch_transfers()
                        
                    render_success(f"새로고침 완료 — 마스터 {len(st.session_state['master_df'])}개, 발주 {len(st.session_state.get('po_df', []))}개")
                except Exception as e:
                    render_error(f"구글 시트 로드 실패: {e}")

    st.divider()
    st.markdown("### ② 채널별 데이터 업로드 (Supabase 연동)")
    
    st.info(
        f"💡 **[공통 설정]** 엑셀 파일의 실제 **조회 기간(시작일~종료일)**을 한 번만 선택해 주세요.\n\n"
        f"면세점 및 도착보장 업로드 시, 시스템이 이 기간 내의 과거 업로드 내역을 조회하여 **'순수하게 추가로 발생한 출고량(Delta)'**만 추출해 냅니다."
    )
    today_global = get_today_kst()
    default_start_global = today_global - timedelta(days=7)
    global_date_range = st.date_input("📅 엑셀 조회 기간 (시작일 - 종료일)", value=(default_start_global, today_global), key="global_date_input")

    if isinstance(global_date_range, tuple) and len(global_date_range) == 2:
        global_start_date, global_end_date = global_date_range
    elif isinstance(global_date_range, tuple) and len(global_date_range) == 1:
        global_start_date = global_end_date = global_date_range[0]
    else:
        global_start_date = global_end_date = global_date_range
    
    channels = ["CK로지스 (WMS)", "도착보장", "롯데면세점", "신라면세점", "신세계면세점", "현대면세점", "US 창고"]
    upload_tabs = st.tabs(channels)
    
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

    # 공통 채널 업로드 UI 함수화
    def render_channel_upload_ui(channel_name: str, tab_idx: int):
        with upload_tabs[tab_idx]:
            st.markdown(f"**[{channel_name}] 마감 엑셀 업로드**")
            
            is_shilla = "신라" in channel_name
            if is_shilla:
                st.markdown("##### 📌 신라면세점은 재고 엑셀과 출고 엑셀을 각각 업로드해 주세요.")
                col1, col2 = st.columns(2)
                with col1:
                    shilla_inv = st.file_uploader(f"📦 재고 엑셀", type=["xls", "xlsx"], key=f"file_inv_{tab_idx}")
                with col2:
                    shilla_ship = st.file_uploader(f"🚚 출고 엑셀", type=["xls", "xlsx"], key=f"file_ship_{tab_idx}")
                files = [f for f in [shilla_inv, shilla_ship] if f is not None]
            else:
                files = st.file_uploader(
                    f"{channel_name} 엑셀 파일 (.xls / .xlsx)",
                    type=["xls", "xlsx"],
                    key=f"file_{tab_idx}",
                    help="선택한 기간 동안의 누적 판매수량 및 기말재고가 포함된 파일을 업로드하세요."
                )
            
            skip_inventory = st.checkbox("🕰️ 과거 데이터 업로드 (체크 시 현재고는 덮어쓰지 않고 출고량만 누적합니다)", key=f"skip_inv_{tab_idx}")

            if files:
                if st.button(f"🚀 {channel_name} 데이터 전송", key=f"btn_{tab_idx}", use_container_width=True):
                    # 매핑 데이터 방어 로직 (마스터 DB가 없을 경우 매핑 불가능)
                    mapping_df = st.session_state.get("mapping_df")
                    if mapping_df is None or mapping_df.empty:
                        render_error("상품 매핑 정보가 없습니다. 상단의 '마스터 DB 새로고침'을 먼저 실행해주세요.")
                        return

                    start_date = global_start_date
                    end_date = global_end_date

                    with st.spinner(f"{channel_name} 파일 파싱 및 전송 중..."):
                        try:
                            all_ship_df = pd.DataFrame()
                            all_inv_df = pd.DataFrame()
                            
                            file_list = files if isinstance(files, list) else [files]
                            
                            for f in file_list:
                                ship_df, inv_df = parse_multi_channel_file(f, end_date, channel_name)
                                all_ship_df = pd.concat([all_ship_df, ship_df])
                                all_inv_df = pd.concat([all_inv_df, inv_df])
                            
                            # [코드 매핑 적용] 
                            if not all_ship_df.empty:
                                all_ship_df = translate_product_codes(all_ship_df, channel_name, mapping_df)
                                all_ship_df["조회시작일"] = start_date
                            if not all_inv_df.empty:
                                all_inv_df = translate_product_codes(all_inv_df, channel_name, mapping_df)
                            
                            # 1. 재고 데이터 업데이트
                            inv_count = 0
                            if not skip_inventory and not all_inv_df.empty:
                                inv_count = upsert_inventory_data(all_inv_df, channel=channel_name)
                            
                            # 2. 출고 데이터 업데이트
                            ship_count = 0
                            filtered_df = pd.DataFrame()
                            if not all_ship_df.empty:
                                ship_count, filtered_df = upsert_ownist_shipping(
                                    all_ship_df, channel=channel_name
                                )
                            
                            # 세션 초기화 및 재조회
                            st.session_state["inventory_df"] = fetch_inventory_data()
                            st.session_state["shipping_df"] = None
                            
                            render_success(f"[{channel_name}] 업데이트 완료! (재고 {inv_count}건, 순수 일일 출고 {ship_count}건 반영)")
                            
                            if not filtered_df.empty:
                                with st.expander(f"📋 {channel_name} 일일 순수 출고량(Delta) 미리보기"):
                                    st.dataframe(filtered_df.head(10), use_container_width=True)
                                
                        except Exception as e:
                            render_error(f"{channel_name} 데이터 처리 오류: {e}")

    # 동적으로 각 채널별 UI 생성
    for idx, ch in enumerate(channels[1:], start=1):
        render_channel_upload_ui(ch, idx)

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
    # 필터 영역 디자인
    fc_reg, fc1, fc2, fc_ch, fc3, fc4 = st.columns([1, 1, 1, 1, 1, 1])
    
    # 0) 지역 필터
    sel_region = fc_reg.selectbox("지역(국가)", ["전체", "한국", "미국"], key="fil_지역_공통")

    # 1) 구분 필터
    구분_opts = ["전체"] + sorted(st.session_state["master_df"]["구분"].dropna().unique().tolist())
    sel_구분 = fc1.selectbox("구분", 구분_opts, key="fil_구분_공통")
    
    # 2) 품목구분 필터
    품목_opts = ["전체"] + sorted(st.session_state["master_df"]["품목구분"].dropna().unique().tolist())
    sel_품목 = fc2.selectbox("품목구분", 품목_opts, key="fil_품목_공통")

    # 3) 채널 필터
    inv_ch = st.session_state["inventory_df"]["채널"].unique().tolist() if not st.session_state["inventory_df"].empty else []
    ship_ch = st.session_state["shipping_df"]["채널"].unique().tolist() if not st.session_state["shipping_df"].empty else []
    
    # 지역별 채널 필터링 적용
    all_channels_available = list(set(inv_ch + ship_ch))
    kr_ch_list = [ch for ch in all_channels_available if ch != "US 창고"]
    us_ch_list = [ch for ch in all_channels_available if ch == "US 창고"]
    
    if sel_region == "한국":
        channel_opts = ["전체"] + sorted(kr_ch_list)
    elif sel_region == "미국":
        channel_opts = ["전체"] + sorted(us_ch_list)
    else:
        channel_opts = ["전체"] + sorted(all_channels_available)
        
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

# 2. 인벤토리/출고 데이터 채널/지역 필터링
filtered_inv = st.session_state["inventory_df"].copy()
filtered_ship = st.session_state["shipping_df"].copy()

# 지역 필터 선 적용
if sel_region == "한국":
    if "채널" in filtered_inv.columns: filtered_inv = filtered_inv[filtered_inv["채널"] != "US 창고"]
    if "채널" in filtered_ship.columns: filtered_ship = filtered_ship[filtered_ship["채널"] != "US 창고"]
elif sel_region == "미국":
    if "채널" in filtered_inv.columns: filtered_inv = filtered_inv[filtered_inv["채널"] == "US 창고"]
    if "채널" in filtered_ship.columns: filtered_ship = filtered_ship[filtered_ship["채널"] == "US 창고"]

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
# 메뉴: 📊 채널별 재고 대시보드
# ════════════════════════════════════════════════
elif menu == "📊 채널별 재고 대시보드":
    try:
        # 보기 옵션 체크박스들 (전역)
        col_chk1, col_chk2 = st.columns(2)
        with col_chk1:
            only_danger_ch = st.checkbox("⚠️ 안전재고 미달만 보기", key="fil_danger_ch")
        with col_chk2:
            hide_zero_ch = st.checkbox("🚫 현재고 0 숨기기", key="fil_hide_zero_ch", value=True)

        st.divider()

        channels_list = ["CK로지스", "도착보장", "롯데면세점", "신라면세점", "신세계면세점", "현대면세점", "US 창고"]
        tabs = st.tabs(channels_list)

        for idx, ch_name in enumerate(channels_list):
            with tabs[idx]:
                st.markdown(f"### {ch_name} 재고 현황")
                
                # 해당 채널의 재고, 출고 데이터 필터링
                ch_inv = filtered_inv[filtered_inv["채널"] == ch_name] if "채널" in filtered_inv.columns else pd.DataFrame(columns=filtered_inv.columns)
                ch_ship = filtered_ship[filtered_ship["채널"] == ch_name] if "채널" in filtered_ship.columns else pd.DataFrame(columns=filtered_ship.columns)

                try:
                    metrics_df_ch = compute_metrics(
                        filtered_master,
                        ch_inv,
                        ch_ship,
                    )
                    # 해당 채널에 재고나 출고 내역이 한 번이라도 있었던 상품만 필터링 (마스터 DB의 껍데기만 나오는 것 방지)
                    valid_codes = set(ch_inv["상품코드"].unique()).union(set(ch_ship["상품코드"].unique()))
                    metrics_df_ch = metrics_df_ch[metrics_df_ch["상품코드"].isin(valid_codes)]
                except Exception as ex:
                    st.error(f"지표 산출 오류 ({ch_name}): {ex}")
                    continue

                if metrics_df_ch.empty:
                    st.info(f"{ch_name}의 등록된 상품이나 데이터가 없습니다.")
                    continue

                render_kpi_row(metrics_df_ch, today)

                view_ch = metrics_df_ch.copy()
                if only_danger_ch:
                    view_ch = view_ch[
                        view_ch["안전재고 미만"].apply(lambda v: isinstance(v, (int, float)) and v < 0)
                    ]
                if hide_zero_ch:
                    view_ch = view_ch[view_ch["현재고"] > 0]

                render_metrics_table(view_ch, key=ch_name)

    except Exception as e:
        render_error(f"오류가 발생했습니다: {e}")
        st.exception(e)



# ════════════════════════════════════════════════
# 메뉴: 🚚 기간별 출고현황
# ════════════════════════════════════════════════
elif menu == "🚚 기간별 출고현황":
    try:
        # 1. 상세 검색 필터 (품목구분 -> 상품)
        col1, col2 = st.columns(2)
        with col1:
            categories = sorted(filtered_master["품목구분"].dropna().unique().tolist())
            selected_category = st.multiselect("📂 품목구분 다중 선택 (비워두면 전체)", categories, key="shipping_cat")
        
        with col2:
            if selected_category:
                prod_list = filtered_master[filtered_master["품목구분"].isin(selected_category)]
            else:
                prod_list = filtered_master
            
            # [상품코드] 상품명 형태로 표시
            product_opts = sorted((prod_list["상품코드"].astype(str) + " - " + prod_list["상품명"].astype(str)).dropna().unique().tolist())
            selected_product = st.multiselect("📦 상품 다중 선택 (비워두면 전체)", product_opts, key="shipping_prod")

        filtered_shipping = filter_shipping_by_date(
            st.session_state["shipping_df"], start_date, end_date
        )
        
        # 일자별 / 월별 데이터 집계
        daily = aggregate_shipping_daily(filtered_shipping)
        monthly = aggregate_shipping_monthly(filtered_shipping)

        # 필터링된 마스터 데이터에 존재하는 상품코드만 남기기 (상품구분 필터 적용)
        daily = daily[daily["상품코드"].isin(filtered_master["상품코드"])]
        monthly = monthly[monthly["상품코드"].isin(filtered_master["상품코드"])]

        # 상품명 조인
        daily = daily.merge(
            filtered_master[["상품코드", "상품명"]],
            on="상품코드", how="left",
        )
        monthly = monthly.merge(
            filtered_master[["상품코드", "상품명"]],
            on="상품코드", how="left",
        )
        
        # 검색어 필터링 적용
        if selected_product:
            # 상품이 선택된 경우, 선택된 상품코드들로 필터링
            selected_codes = [p.split(" - ")[0] for p in selected_product]
            daily = daily[daily["상품코드"].astype(str).isin(selected_codes)]
            monthly = monthly[monthly["상품코드"].astype(str).isin(selected_codes)]
        elif selected_category:
            # 상품은 선택 안 했지만, 품목구분이 선택된 경우
            cat_codes = prod_list["상품코드"].tolist()
            daily = daily[daily["상품코드"].isin(cat_codes)]
            monthly = monthly[monthly["상품코드"].isin(cat_codes)]

        # 탭 분리
        tab1, tab2 = st.tabs(["일자별 출고현황", "월별 출고현황"])
        
        with tab1:
            render_shipping_table(daily, start_date, end_date, period_type="daily")
            
        with tab2:
            render_shipping_table(monthly, start_date, end_date, period_type="monthly")

    except Exception as e:
        render_error(f"출고현황 조회 오류: {e}")
        st.exception(e)


# ════════════════════════════════════════════════
# 메뉴: 📦 발주 및 입고현황
# ════════════════════════════════════════════════
elif menu == "📦 발주 및 입고현황":
    st.markdown('<div class="sec-title">📦 발주 및 입고현황 (PO & Inbound)</div>', unsafe_allow_html=True)
    
    po_df = st.session_state.get("po_df")
    if po_df is None or po_df.empty:
        st.info("데이터 설정 메뉴에서 Google Sheets에 '발주' 시트를 생성하고 데이터를 불러와주세요.\n\n필수 컬럼: 외주처, 상품코드, 상품명, 발주수량, 납기예정일, 입고상태")
    else:
        # 필터링 적용 (구분, 품목구분 필터)
        disp_po = po_df[po_df["상품코드"].isin(filtered_master["상품코드"])].copy()
        
        # 상품명 매핑(선택적) - 마스터 기준 (상품코드 중복으로 인한 행 증식 방지)
        master_names = filtered_master[["상품코드", "상품명"]].drop_duplicates(subset=["상품코드"])
        disp_po = disp_po.merge(master_names, on="상품코드", how="left", suffixes=("_po", "_master"))
        disp_po["상품명"] = disp_po["상품명_master"].fillna(disp_po["상품명_po"])
        
        from ui.po_calendar import render_po_calendar
        render_po_calendar(disp_po)
        
        st.divider()
        
        col_summary1, col_summary2 = st.columns(2)
        with col_summary1:
            total_qty = disp_po["발주수량"].sum()
            st.metric("총 발주/입고예정 수량", f"{total_qty:,.0f} EA")
        with col_summary2:
            pending_qty = disp_po[disp_po["입고상태"] != "완료"]["발주수량"].sum()
            st.metric("미완료 수량", f"{pending_qty:,.0f} EA")
            
        with st.expander("📝 발주 및 입고 상세 데이터 테이블 보기", expanded=True):
            st.dataframe(
                disp_po[["외주처", "상품명", "발주수량", "납기예정일", "입고상태"]].style.format({"발주수량": "{:,.0f}"}),
                use_container_width=True
            )

# ════════════════════════════════════════════════
# 메뉴: 🔮 S&OP 시뮬레이션
# ════════════════════════════════════════════════
elif menu == "🔮 S&OP 시뮬레이션":
    try:
        render_sop_simulation(
            filtered_master,
            st.session_state["inventory_df"],
            st.session_state["shipping_df"],
            st.session_state.get("po_df"),
            today
        )
    except Exception as e:
        render_error(f"S&OP 시뮬레이션 오류: {e}")
        st.exception(e)

# ════════════════════════════════════════════════
# 메뉴: 🌐 다단계 예상재고
# ════════════════════════════════════════════════
elif menu == "🌐 다단계 예상재고":
    from ui.projected_inventory import render_projected_inventory
    try:
        render_projected_inventory(
            filtered_master,
            st.session_state["inventory_df"],
            st.session_state["shipping_df"],
            st.session_state.get("po_df"),
            st.session_state.get("transfer_df")
        )
    except Exception as e:
        render_error(f"예상재고 시뮬레이션 오류: {e}")
        st.exception(e)

# ════════════════════════════════════════════════
# 메뉴: 🚢 선적 및 이동 관리
# ════════════════════════════════════════════════
elif menu == "🚢 선적 및 이동 관리":
    from ui.transfer_manager import render_transfer_manager
    try:
        render_transfer_manager(filtered_master)
    except Exception as e:
        render_error(f"선적 관리 오류: {e}")
        st.exception(e)
