"""
ui/components.py  ─  Streamlit UI 렌더링 전담 모듈
데이터 처리 로직 전혀 없음. Antigravity 이관 시 이 파일만 교체.
"""

import streamlit as st
import pandas as pd
from datetime import date


# ════════════════════════════════════════════════
# 페이지 설정 & 전역 CSS
# ════════════════════════════════════════════════
def setup_page():
    st.set_page_config(
        page_title="재고·출고 대시보드",
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap');

/* ── 전역 폰트 및 배경 ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #f8fafc !important;
    background: #f8fafc !important;
    color: #334155 !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}

[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.02) !important;
}

[data-testid="stHeader"] {
    background: transparent;
}

/* ── 헤더 ── */
.dh-wrap {
    display: flex;
    align-items: center;
    gap: 16px;
    padding-bottom: 24px;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 28px;
    font-family: 'Outfit', sans-serif;
}
.dh-wrap .logo {
    font-size: 2.5rem;
    line-height: 1;
}
.dh-wrap h1 {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.5px;
}
.dh-wrap .sub {
    font-size: 0.85rem;
    color: #64748b;
    margin-top: 4px;
    font-weight: 500;
}

/* ── KPI 카드 ── */
.kpi-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 32px;
}
.kpi-card {
    flex: 1;
    min-width: 180px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px -1px rgba(0, 0, 0, 0.02);
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    font-family: 'Outfit', sans-serif;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    border-color: #cbd5e1;
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
    background: var(--ac, #3b82f6);
}
.kpi-card .lbl {
    font-size: 0.75rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
    font-weight: 600;
}
.kpi-card .val {
    font-size: 1.85rem;
    font-weight: 800;
    color: #0f172a;
    line-height: 1.2;
}
.kpi-card .dlt {
    font-size: 0.78rem;
    color: #64748b;
    margin-top: 6px;
    font-weight: 500;
}
.kpi-card.ok     { --ac: #10b981; }
.kpi-card.warn   { --ac: #f59e0b; }
.kpi-card.danger { --ac: #ef4444; }
.kpi-card.info   { --ac: #6366f1; }

/* ── 섹션 타이틀 ── */
.sec-title {
    font-size: 0.9rem;
    font-weight: 700;
    color: #334155;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding-bottom: 10px;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 18px;
    font-family: 'Outfit', sans-serif;
}

/* ── 안내 박스 ── */
.info-box {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 16px 20px;
    font-size: 0.88rem;
    color: #475569;
    margin-bottom: 20px;
    line-height: 1.5;
}

/* ── Streamlit UI Elements 오버라이드 ── */
div.stDownloadButton > button {
    background-color: #ffffff !important;
    color: #475569 !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 8px !important;
    padding: 8px 18px !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}
div.stDownloadButton > button:hover {
    background-color: #f8fafc !important;
    color: #0f172a !important;
    border-color: #94a3b8 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05) !important;
}
div.stDownloadButton > button:active {
    transform: translateY(0px) !important;
}
</style>
"""


# ════════════════════════════════════════════════
# 헤더
# ════════════════════════════════════════════════
def render_header():
    st.markdown("""
    <div class="dh-wrap">
        <span class="logo">📦</span>
        <div>
            <h1>재고 · 출고 대시보드</h1>
            <div class="sub">Inventory &amp; Shipping Intelligence · KST 기준</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════
# KPI 카드
# ════════════════════════════════════════════════
def render_kpi_row(metrics_df: pd.DataFrame, today):
    total      = len(metrics_df)
    danger_cnt = int(
        metrics_df["안전재고 미만"]
        .apply(lambda v: isinstance(v, (int, float)) and v < 0)
        .sum()
    )
    zero_stock = int((metrics_df["현재고"] == 0).sum())
    no_ship    = int(
        metrics_df["사용가능(일)"]
        .apply(lambda v: v == "출고없음")
        .sum()
    )

    st.markdown(f"""
    <div class="kpi-row">
      <div class="kpi-card ok">
        <div class="lbl">전체 품목</div>
        <div class="val">{total:,}</div>
        <div class="dlt">마스터 DB 등록 상품</div>
      </div>
      <div class="kpi-card danger">
        <div class="lbl">안전재고 미달</div>
        <div class="val">{danger_cnt:,}</div>
        <div class="dlt">즉시 발주 검토 필요</div>
      </div>
      <div class="kpi-card warn">
        <div class="lbl">재고 없음</div>
        <div class="val">{zero_stock:,}</div>
        <div class="dlt">현재고 0 품목</div>
      </div>
      <div class="kpi-card info">
        <div class="lbl">출고 이력 없음</div>
        <div class="val">{no_ship:,}</div>
        <div class="dlt">최근 90일 출고 0</div>
      </div>
      <div class="kpi-card">
        <div class="lbl">기준일 (KST)</div>
        <div class="val" style="font-size:1.05rem;">{today.strftime('%Y-%m-%d')}</div>
        <div class="dlt">최근 90일 출고 기준</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════
# 재고 지표 테이블
# ════════════════════════════════════════════════
def render_metrics_table(metrics_df: pd.DataFrame):
    st.markdown('<div class="sec-title">📊 재고 지표 테이블</div>', unsafe_allow_html=True)

    display = metrics_df.copy()

    # 소수점 포맷
    num_cols = [
        "현재고", "3개월 총출고량", "3개월 월평균 출고량",
        "3개월 일평균 출고량", "안전재고", "안전재고 미만",
    ]
    for col in num_cols:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda v: f"{v:,.1f}" if isinstance(v, (int, float)) else v
            )
    for col in ["사용가능(월)", "사용가능(일)"]:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda v: f"{v:.1f}" if isinstance(v, (int, float)) else v
            )

    # 행 하이라이트
    def _highlight(row):
        try:
            raw_val = metrics_df.loc[row.name, "안전재고 미만"]
            if isinstance(raw_val, (int, float)) and raw_val < 0:
                return ["background-color:#fee2e2;color:#b91c1c;font-weight:500;"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    styled = display.style.apply(_highlight, axis=1)
    st.dataframe(styled, use_container_width=True, height=500)

    csv = metrics_df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ 지표 테이블 CSV 다운로드",
        data=csv,
        file_name=f"재고지표_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ════════════════════════════════════════════════
# 일자별 출고현황 테이블
# ════════════════════════════════════════════════
def render_shipping_table(daily_df: pd.DataFrame, start_date, end_date):
    st.markdown(
        f'<div class="sec-title">🚚 일자별 출고현황 ({start_date} ~ {end_date})</div>',
        unsafe_allow_html=True,
    )

    if daily_df.empty:
        st.info("선택한 기간에 출고 데이터가 없습니다.")
        return

    # 피벗: 행=상품코드+상품명, 열=날짜
    pivot_index = ["상품코드", "상품명"] if "상품명" in daily_df.columns else ["상품코드"]
    pivot = daily_df.pivot_table(
        index=pivot_index,
        columns="출고일자",
        values="출고수량",
        aggfunc="sum",
        fill_value=0,
    )
    pivot.columns = [str(c) for c in pivot.columns]
    pivot["합계"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("합계", ascending=False).reset_index()

    st.dataframe(pivot, use_container_width=True, height=460)

    csv = pivot.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "⬇️ 출고현황 CSV 다운로드",
        data=csv,
        file_name=f"출고현황_{start_date}_{end_date}.csv",
        mime="text/csv",
    )


# ════════════════════════════════════════════════
# 알림
# ════════════════════════════════════════════════
def render_error(msg: str):
    st.error(f"❌ {msg}")

def render_success(msg: str):
    st.success(f"✅ {msg}")
