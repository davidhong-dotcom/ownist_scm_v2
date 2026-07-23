import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from data.processor import compute_metrics

import requests

def generate_mock_schedules(start_date: date, weeks: int = 8, lead_time_days: int = 35):
    """
    Generate mock shipping schedules for the next N weeks.
    Departs every Thursday.
    """
    schedules = []
    # Find the next Thursday
    days_ahead = 3 - start_date.weekday() # Thursday is 3
    if days_ahead < 0: 
        days_ahead += 7
    next_thursday = start_date + timedelta(days=days_ahead)
    
    for i in range(weeks):
        etd = next_thursday + timedelta(weeks=i)
        eta = etd + timedelta(days=lead_time_days)
        cutoff = etd - timedelta(days=4) # Cut-off is usually a few days before ETD (Sunday)
        
        schedules.append({
            "Vessel": f"HMM MOCK-{100+i}E",
            "Cut-off (서류/화물 마감)": cutoff.strftime("%Y-%m-%d"),
            "ETD (부산 출항)": etd.strftime("%Y-%m-%d"),
            "ETA (LA 입항/입고)": eta.strftime("%Y-%m-%d"),
            "Lead Time": f"{lead_time_days}일"
        })
        
    return pd.DataFrame(schedules)

@st.cache_data(ttl=3600)
def fetch_hmm_schedules(start_date_str: str, lead_time_days: int = 35) -> pd.DataFrame:
    """
    Fetch Port-to-Port schedules from HMM API if API key is provided in secrets.
    Fallback to mock schedules if not available or API call fails.
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    
    # 1. secrets에서 API Key 확인
    api_key = None
    try:
        api_key = st.secrets.get("HMM_API_KEY")
    except Exception:
        pass
        
    if not api_key:
        return generate_mock_schedules(start_date, weeks=12, lead_time_days=lead_time_days)
        
    try:
        # TODO: 실제 HMM API Endpoint와 응답 파싱 로직으로 교체 필요
        url = "https://api.hmm21.com/v1/schedule/port-to-port" # 예시 URL
        headers = {
            "Authorization": f"Bearer {api_key}", # 또는 다른 인증 방식
            "Content-Type": "application/json"
        }
        params = {
            "pol": "KRPUS",
            "pod": "USLAX",
            "startDate": start_date_str,
            "endDate": (start_date + timedelta(days=90)).strftime("%Y-%m-%d")
        }
        
        # 실제 호출 (현재는 Docs가 없으므로 주석 처리 및 예외 발생 유도)
        # response = requests.get(url, headers=headers, params=params, timeout=10)
        # response.raise_for_status()
        # data = response.json()
        
        # 만약 성공적으로 파싱했다면 아래와 같은 DataFrame 포맷으로 리턴해야 합니다.
        # return pd.DataFrame(parsed_schedules)
        
        raise NotImplementedError("API 연동 상세 로직(응답 파싱 등)은 명세서 확인 후 완성됩니다.")
        
    except Exception as e:
        # API 통신 실패 시 우회(Fallback)
        # st.warning(f"⚠️ HMM API 연동 실패 (사유: {e}). 임시 모의 스케줄로 대체합니다.")
        return generate_mock_schedules(start_date, weeks=12, lead_time_days=lead_time_days)

def render_la_shipping_recommendation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, today: date):
    st.markdown('<div class="sec-title">🚢 미국 선적 일정 추천 (Busan -> LA)</div>', unsafe_allow_html=True)
    
    if master_df is None or inventory_df is None or shipping_df is None or shipping_df.empty:
        st.info("데이터가 충분하지 않아 시뮬레이션을 실행할 수 없습니다. 데이터를 먼저 불러와 주세요.")
        return
        
    st.markdown("""
    <div class="info-box">
    <strong>💡 미국 창고(CGETC) 선적 일정 추천</strong><br>
    미국 창고의 상품별 <strong>예상 소진일</strong>을 기반으로, 재고 부족 사태를 방지하기 위해 
    미리 예약해야 하는 <strong>추천 선적 스케줄(Recommended Vessel)</strong>을 안내합니다.<br>
    현재 실제 스케줄 데이터가 연동되지 않아 <strong>매주 목요일 출항하는 가상 스케줄</strong>을 기준으로 매칭됩니다.
    </div>
    """, unsafe_allow_html=True)

    # 설정 패널
    with st.expander("⚙️ 스케줄 시뮬레이션 설정", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            lead_time = st.number_input("해상 운송 리드타임 (일)", min_value=10, max_value=100, value=35, step=1, 
                                        help="출항일(ETD)부터 LA 창고 입고(ETA)까지 걸리는 총 기간입니다. 최근 지연 반영.")
        with col2:
            safety_buffer = st.number_input("도착 안전 여유일 (일)", min_value=0, max_value=30, value=7, step=1,
                                            help="재고 소진일보다 최소 며칠 전에 도착(ETA)해야 하는지 설정합니다.")
    
    st.divider()

    # 1. CGETC 데이터 필터링
    us_inv = inventory_df[inventory_df["채널"] == "CGETC"] if "채널" in inventory_df.columns else pd.DataFrame()
    us_ship = shipping_df[shipping_df["채널"] == "CGETC"] if "채널" in shipping_df.columns else pd.DataFrame()
    
    if us_inv.empty:
        st.warning("CGETC(미국) 창고의 현재고 데이터가 없습니다. [데이터 설정]에서 미국 창고 재고를 업로드해 주세요.")
        return

    # 2. 예상 소진일 계산 (compute_metrics 활용)
    with st.spinner("예상 소진일 산출 중..."):
        try:
            metrics_df = compute_metrics(master_df, us_inv, us_ship)
        except Exception as e:
            st.error(f"지표 산출 중 오류가 발생했습니다: {e}")
            return
            
    # "무한대(∞)"나 "출고없음" 제거
    valid_metrics = metrics_df[~metrics_df["예상소진일"].isin(["∞", "출고없음", "-"])].copy()
    if valid_metrics.empty:
        st.info("현재 예상 소진일을 계산할 수 있는 품목이 없습니다. (최근 90일 출고 이력이 부족할 수 있습니다.)")
        return
        
    # 날짜형으로 변환 및 빠른 소진일 순으로 정렬
    valid_metrics["소진일자_dt"] = pd.to_datetime(valid_metrics["예상소진일"])
    valid_metrics = valid_metrics.sort_values("소진일자_dt").reset_index(drop=True)
    
    # 3. 스케줄 로드 (API Key가 없으면 내부적으로 모의 스케줄 반환)
    schedules_df = fetch_hmm_schedules(today.strftime("%Y-%m-%d"), lead_time_days=lead_time)
    schedules_df["ETA_dt"] = pd.to_datetime(schedules_df["ETA (LA 입항/입고)"])
    
    st.markdown("### 🎯 상품별 선적 추천")
    
    # 화면 렌더링
    for idx, row in valid_metrics.iterrows():
        prod_name = row["상품명"]
        expiry_date = row["소진일자_dt"]
        target_eta = expiry_date - timedelta(days=safety_buffer)
        
        # 목표 ETA(소진일 - 여유일)보다 이전에 도착하는 스케줄 중 가장 늦은 스케줄(JIT) 찾기
        possible_vessels = schedules_df[schedules_df["ETA_dt"] <= target_eta]
        
        with st.container():
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown(f"#### 📦 {prod_name}")
                st.write(f"- **현재고**: {row['현재고']:,.0f}개")
                st.write(f"- **예상 소진일**: **<span style='color:#d32f2f;'>{row['예상소진일']}</span>**", unsafe_allow_html=True)
                st.write(f"- **필요 도착일(ETA)**: {target_eta.strftime('%Y-%m-%d')} 이전")
                
            with c2:
                if possible_vessels.empty:
                    st.error("🚨 **추천 가능한 선적 스케줄이 없습니다!**\\n재고 소진일이 너무 임박하여 해상 운송으로는 기한을 맞출 수 없습니다. **항공 운송(Air Freight)**을 고려하세요.")
                else:
                    # JIT(Just-in-time) 추천: 가능한 스케줄 중 가장 마지막(최신) 스케줄
                    recommended = possible_vessels.iloc[-1]
                    
                    st.success(f"✅ **추천 선적 (Recommended Vessel): {recommended['Vessel']}**")
                    st.write(f"⏰ **마감(Cut-off)**: {recommended['Cut-off (서류/화물 마감)']}")
                    st.write(f"🚢 **ETD(출항)**: {recommended['ETD (부산 출항)']}")
                    st.write(f"🛬 **ETA(입고)**: {recommended['ETA (LA 입항/입고)']}")
                    
            st.divider()
            
    st.markdown("### 📅 전체 모의 선적 스케줄 (Busan -> LA)")
    st.dataframe(schedules_df.drop(columns=["ETA_dt"]), use_container_width=True)
