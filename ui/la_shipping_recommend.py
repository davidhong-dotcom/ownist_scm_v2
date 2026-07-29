import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from data.processor import compute_metrics
import requests
import urllib.parse
import xml.etree.ElementTree as ET

def generate_mock_schedules(start_date: date, weeks: int = 8, lead_time_days: int = 35, port_name: str = "부산항"):
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
        eta = etd + timedelta(days=14)
        cutoff = etd - timedelta(days=4) # Cut-off is usually a few days before ETD (Sunday)
        
        schedules.append({
            "Vessel": f"MOCK VESSEL-{100+i}E",
            "Cut-off (서류/화물 마감)": cutoff.strftime("%Y-%m-%d"),
            "ETD (출항)": etd.strftime("%Y-%m-%d"),
            "ETA (LA 입항)": eta.strftime("%Y-%m-%d"),
            "Lead Time": "14일"
        })
        
    return pd.DataFrame(schedules)

@st.cache_data(ttl=3600)
def fetch_openapi_schedules(start_date_str: str, prt_ag_cd: str, lead_time_days: int = 35, port_name: str = "부산항") -> pd.DataFrame:
    """
    Fetch Port-to-Port schedules from OpenAPI (선박운항정보) if API key is provided in secrets.
    Fallback to mock schedules if not available, API call fails, or no vessels to LA are found.
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date_str = (start_date + timedelta(days=30)).strftime("%Y%m%d")
    sde_str = start_date.strftime("%Y%m%d")
    
    api_key = None
    try:
        if "OPENAPI_SERVICE_KEY" in st.secrets:
            api_key = st.secrets["OPENAPI_SERVICE_KEY"]
        else:
            for k, v in st.secrets.items():
                if hasattr(v, "get") and "OPENAPI_SERVICE_KEY" in v:
                    api_key = v["OPENAPI_SERVICE_KEY"]
                    break
    except Exception:
        pass
        
    if not api_key:
        st.warning("⚠️ `secrets.toml`에서 `OPENAPI_SERVICE_KEY`를 찾을 수 없어 선박 스케줄을 조회할 수 없습니다.")
        return pd.DataFrame(columns=["Vessel", "Cut-off (서류/화물 마감)", "ETD (출항)", "ETA (LA 입항)", "Lead Time"])
        
    try:
        url = "http://apis.data.go.kr/1192000/VsslEtrynd5/Info5"
        api_key_unquoted = urllib.parse.unquote(api_key)
        
        parsed_schedules = []
        
        # 최대 10페이지(약 500건)까지 조회
        for page in range(1, 11):
            params = {
                "serviceKey": api_key_unquoted,
                "prtAgCd": prt_ag_cd,
                "sde": sde_str,
                "ede": end_date_str,
                "deGb": "O", # 출항일 기준
                "pageNo": str(page),
                "numOfRows": "50" 
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            items = root.findall(".//item")
            
            if not items:
                break
                
            for item in items:
                dstnNatPrtCd = item.findtext("dstnNatPrtCd", "")
                dstnPrtNm = item.findtext("dstnPrtNm", "")
                
                # 필터링: 목적지가 미국 LA/Long Beach 인 경우
                if "USLAX" in dstnNatPrtCd or "USLGB" in dstnNatPrtCd or "LOS ANGELES" in dstnPrtNm.upper() or "LONG BEACH" in dstnPrtNm.upper():
                    vsslNm = item.findtext("vsslNm", "Unknown Vessel")
                    
                    details = item.findall(".//detail")
                    for det in details:
                        tkoff = det.findtext("tkoffPrrrnDt", "")
                        eta = det.findtext("dstnEtryptDt", "")
                        
                        if tkoff:
                            try:
                                etd_dt = datetime.strptime(tkoff, "%Y-%m-%d %H:%M:%S")
                                etd_str = etd_dt.strftime("%Y-%m-%d")
                                cutoff_str = (etd_dt - timedelta(days=4)).strftime("%Y-%m-%d")
                                
                                if eta:
                                    try:
                                        eta_dt = datetime.strptime(eta, "%Y-%m-%d %H:%M:%S")
                                        eta_str = eta_dt.strftime("%Y-%m-%d")
                                        lt = (eta_dt.date() - etd_dt.date()).days
                                    except Exception:
                                        eta_str = (etd_dt + timedelta(days=14)).strftime("%Y-%m-%d")
                                        lt = 14
                                else:
                                    eta_str = (etd_dt + timedelta(days=14)).strftime("%Y-%m-%d")
                                    lt = 14
                                
                                parsed_schedules.append({
                                    "Vessel": f"{vsslNm}",
                                    "Cut-off (서류/화물 마감)": cutoff_str,
                                    "ETD (출항)": etd_str,
                                    "ETA (LA 입항)": eta_str,
                                    "Lead Time": f"{lt}일"
                                })
                            except Exception:
                                pass
            
            # 한 번에 불러오는 건수가 50건 미만이면 다음 페이지가 없음
            if len(items) < 50:
                break
                            
        if parsed_schedules:
            df = pd.DataFrame(parsed_schedules).drop_duplicates().sort_values("ETD (출항)")
            df = df[df["ETD (출항)"] >= start_date_str]
            if not df.empty:
                # 마지막 선박 출항일 이후의 가상 예측 스케줄(12주) 자동 생성 (장기 계획용)
                last_etd_str = df.iloc[-1]["ETD (출항)"]
                last_etd_dt = datetime.strptime(last_etd_str, "%Y-%m-%d").date()
                
                # 다음주 목요일을 첫 기준으로 설정
                days_ahead = 3 - last_etd_dt.weekday() # 3: Thursday
                if days_ahead <= 0:
                    days_ahead += 7
                next_thursday = last_etd_dt + timedelta(days=days_ahead)
                
                projected = []
                for i in range(12):
                    etd = next_thursday + timedelta(weeks=i)
                    eta = etd + timedelta(days=14)
                    cutoff = etd - timedelta(days=4)
                    
                    projected.append({
                        "Vessel": f"🌟예상 정기선 (장기계획용)",
                        "Cut-off (서류/화물 마감)": cutoff.strftime("%Y-%m-%d"),
                        "ETD (출항)": etd.strftime("%Y-%m-%d"),
                        "ETA (LA 입항)": eta.strftime("%Y-%m-%d"),
                        "Lead Time": "14일"
                    })
                    
                proj_df = pd.DataFrame(projected)
                return pd.concat([df, proj_df], ignore_index=True)
                
        # 조건에 맞는 선박이 없으면 빈 DataFrame 반환
        return pd.DataFrame(columns=["Vessel", "Cut-off (서류/화물 마감)", "ETD (출항)", "ETA (LA 입항)", "Lead Time"])
        
    except Exception as e:
        st.error(f"🚨 공공데이터 API 통신 중 오류가 발생했습니다: {e}")
        return pd.DataFrame(columns=["Vessel", "Cut-off (서류/화물 마감)", "ETD (출항)", "ETA (LA 입항)", "Lead Time"])

def render_la_shipping_recommendation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, today: date):
    st.markdown('<div class="sec-title">🚢 미국 선적 일정 추천 (KR ➔ LA)</div>', unsafe_allow_html=True)
    
    if master_df is None or inventory_df is None or shipping_df is None or shipping_df.empty:
        st.info("데이터가 충분하지 않아 시뮬레이션을 실행할 수 없습니다. 데이터를 먼저 불러와 주세요.")
        return
        
    st.markdown("""
    <div class="info-box">
    <strong>💡 미국 창고(CGETC) 선적 일정 추천</strong><br>
    미국 창고의 상품별 <strong>예상 소진일</strong>을 기반으로, 재고 부족 사태를 방지하기 위해 
    미리 예약해야 하는 <strong>추천 선적 스케줄(Recommended Vessel)</strong>을 안내합니다.<br>
    공공데이터포털(선박운항정보) OpenAPI를 통해 <strong>실제 출항 예정 선박</strong>을 우선 매칭하며, 
    조회된 선박이 부족할 경우 가상의 정기선 스케줄로 자동 연장(Fallback)됩니다.
    </div>
    """, unsafe_allow_html=True)

    # 설정 패널
    with st.expander("⚙️ 스케줄 시뮬레이션 설정", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 020: 부산, 030: 인천
            port_opts = {"부산항": "020", "인천항": "030"}
            selected_port_name = st.selectbox("출발지 (POL) 선택", list(port_opts.keys()))
            selected_prt_cd = port_opts[selected_port_name]
        with col2:
            lead_time = st.number_input("총 리드타임 (해상14일+통관/내륙+창고입고)", min_value=10, max_value=100, value=35, step=1, 
                                        help="단순 해상 운송(약 14일)뿐만 아니라, LA 항만 하역/통관 대기 및 CGETC 창고까지의 내륙 운송/입고 소요 시간을 모두 합친 '실제 판매 가능까지의 총 소요 기간'을 입력합니다. (안전 기준 30~35일 권장)")
        with col3:
            safety_buffer = st.number_input("도착 안전 여유일 (일)", min_value=0, max_value=30, value=7, step=1,
                                            help="재고 소진일보다 최소 며칠 전에 도착(ETA)해야 하는지 설정합니다.")
    
    st.divider()

    us_inv = inventory_df[inventory_df["채널"] == "CGETC"] if "채널" in inventory_df.columns else pd.DataFrame()
    us_ship = shipping_df[shipping_df["채널"] == "CGETC"] if "채널" in shipping_df.columns else pd.DataFrame()
    
    if us_inv.empty:
        st.warning("CGETC(미국) 창고의 현재고 데이터가 없습니다. [데이터 설정]에서 미국 창고 재고를 업로드해 주세요.")
        return

    with st.spinner("예상 소진일 산출 중..."):
        try:
            metrics_df = compute_metrics(master_df, us_inv, us_ship)
        except Exception as e:
            st.error(f"지표 산출 중 오류가 발생했습니다: {e}")
            return
            
    valid_metrics = metrics_df[~metrics_df["예상소진일"].isin(["∞", "출고없음", "-"])].copy()
    if valid_metrics.empty:
        st.info("현재 예상 소진일을 계산할 수 있는 품목이 없습니다. (최근 90일 출고 이력이 부족할 수 있습니다.)")
        return
        
    valid_metrics["소진일자_dt"] = pd.to_datetime(valid_metrics["예상소진일"])
    valid_metrics = valid_metrics.sort_values("소진일자_dt").reset_index(drop=True)
    
    # 3. 스케줄 로드 (OpenAPI 호출)
    schedules_df = fetch_openapi_schedules(today.strftime("%Y-%m-%d"), prt_ag_cd=selected_prt_cd, lead_time_days=lead_time, port_name=selected_port_name)
    schedules_df["ETA_dt"] = pd.to_datetime(schedules_df["ETA (LA 입항)"])
    
    st.markdown(f"### 🎯 상품별 선적 추천 ({selected_port_name} ➔ 미국 LA)")
    
    for idx, row in valid_metrics.iterrows():
        prod_name = row["상품명"]
        expiry_date = row["소진일자_dt"]
        
        # 항구(Port) 입항 후 창고 입고까지 걸리는 내륙 소요 시간 (총 리드타임 - 해상 14일)
        inland_days = max(0, lead_time - 14) 
        
        # 항구(Port)에 늦어도 도착해야 하는 목표 입항일
        target_port_eta = expiry_date - timedelta(days=safety_buffer + inland_days)
        
        possible_vessels = schedules_df[schedules_df["ETA_dt"] <= target_port_eta]
        
        with st.container():
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown(f"#### 📦 {prod_name}")
                st.write(f"- **현재고**: {row['현재고']:,.0f}개")
                st.write(f"- **예상 소진일**: **<span style='color:#d32f2f;'>{row['예상소진일']}</span>**", unsafe_allow_html=True)
                st.write(f"- **필요 입항일(Port ETA)**: {target_port_eta.strftime('%Y-%m-%d')} 이전")
                
            with c2:
                if possible_vessels.empty:
                    st.error(f"🚨 **추천 가능한 선적 스케줄이 없습니다!**  \n창고 입고를 위해 늦어도 **{target_port_eta.strftime('%Y-%m-%d')}** 까지는 항구에 도착(ETA)해야 하지만, 해상 운송으로는 기한을 맞출 수 없습니다. **항공 운송(Air Freight)**을 고려하세요.")
                else:
                    recommended = possible_vessels.iloc[-1]
                    
                    is_proj = "🌟예상 정기선" in recommended['Vessel']
                    badge = "💡 가상 스케줄(장기계획용)" if is_proj else "🚢 확정 스케줄(OpenAPI)"
                    
                    st.success(f"✅ **추천 선적 (Recommended Vessel): {recommended['Vessel']}**  `{badge}`")
                    st.write(f"⏰ **마감(Cut-off)**: {recommended['Cut-off (서류/화물 마감)']}")
                    st.write(f"🚢 **ETD({selected_port_name} 출항)**: {recommended['ETD (출항)']}")
                    st.write(f"🛬 **ETA(LA 항구 입항)**: {recommended['ETA (LA 입항)']}")
                    
            st.divider()
            st.divider()
            
    # 전체 선적 스케줄 렌더링 (부산항, 인천항 모두 고정 노출)
    busan_schedules_df = fetch_openapi_schedules(today.strftime("%Y-%m-%d"), prt_ag_cd="020", lead_time_days=lead_time, port_name="부산항")
    icn_schedules_df = fetch_openapi_schedules(today.strftime("%Y-%m-%d"), prt_ag_cd="030", lead_time_days=lead_time, port_name="인천항")
    
    st.markdown("### 📅 전체 선적 스케줄 (부산항 ➔ LA)")
    if busan_schedules_df.empty:
        st.info("현재 공공데이터에 등록된 부산항 출항 스케줄이 없습니다.")
    else:
        st.dataframe(busan_schedules_df.drop(columns=["ETA_dt"], errors="ignore"), use_container_width=True)
    
    st.markdown("### 📅 전체 선적 스케줄 (인천항 ➔ LA)")
    if icn_schedules_df.empty:
        st.info("현재 공공데이터에 등록된 인천항 출항 스케줄이 없습니다.")
    else:
        st.dataframe(icn_schedules_df.drop(columns=["ETA_dt"], errors="ignore"), use_container_width=True)
