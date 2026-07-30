import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from data.processor import compute_metrics
import requests
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os

def load_scraped_schedules(start_date_str: str, port_name: str) -> pd.DataFrame:
    """
    스크래퍼가 수집하여 Supabase DB에 저장한 마스터 스케줄 데이터를 불러옵니다.
    """
    try:
        if "supabase" not in st.secrets:
            return pd.DataFrame()
            
        from supabase import create_client, Client
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase: Client = create_client(url, key)
        
        # 출발지에 맞게 필터링 (부산항=KRPUS, 인천항=KRINC)
        origin_code = "KRPUS" if port_name == "부산항" else "KRINC"
        
        response = supabase.table("shipping_master_schedules").select("*").eq("origin_port", origin_code).execute()
        data = response.data
        
        if not data:
            return pd.DataFrame()
            
        # UI DataFrame 형식으로 변환
        mapped = []
        for d in data:
            vessel_full = f"{d.get('vessel_name', '')} {d.get('voyage_no', '')}".strip()
            
            etd_str = d.get("etd", "")
            eta_str = d.get("eta", "")
            
            # ETA - ETD 계산
            lt_days = 14
            if etd_str and eta_str:
                try:
                    etd_dt = datetime.strptime(etd_str, "%Y-%m-%d").date()
                    eta_dt = datetime.strptime(eta_str, "%Y-%m-%d").date()
                    lt_days = (eta_dt - etd_dt).days
                except Exception:
                    lt_days = d.get('transit_time_days', 14)
                    if lt_days is None: lt_days = 14
            else:
                lt_days = d.get('transit_time_days', 14)
                if lt_days is None: lt_days = 14
                
            mapped.append({
                "선적사": d.get("carrier", ""),
                "Vessel": vessel_full, 
                "Cut-off (화물 반입 마감)": d.get("cargo_cutoff", ""),
                "ETD (출항)": etd_str,
                "ETA (LA 입항)": eta_str,
                "Lead Time": f"{lt_days}일"
            })
            
        df = pd.DataFrame(mapped)
        # 화물 반입 마감일이 오늘(start_date_str)보다 과거인 스케줄은 제외
        df = df[df["Cut-off (화물 반입 마감)"] >= start_date_str]
        df = df.reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Error loading scraped schedules from Supabase: {e}")
        return pd.DataFrame(columns=["선적사", "Vessel", "Cut-off (화물 반입 마감)", "ETD (출항)", "ETA (LA 입항)", "Lead Time"])

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
def fetch_schedules(start_date_str: str, port_name: str = "부산항") -> pd.DataFrame:
    """
    스크래핑된 마스터 스케줄을 가져옵니다.
    """
    scraped_df = load_scraped_schedules(start_date_str, port_name)
    if not scraped_df.empty:
        scraped_df = scraped_df[['선적사', 'Vessel', 'Cut-off (화물 반입 마감)', 'ETD (출항)', 'ETA (LA 입항)', 'Lead Time']]
        return scraped_df
    return pd.DataFrame(columns=["선적사", "Vessel", "Cut-off (화물 반입 마감)", "ETD (출항)", "ETA (LA 입항)", "Lead Time"])

def render_la_shipping_recommendation(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, today: date):
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.markdown('<div class="sec-title">🚢 미국 선적 일정 추천 (KR ➔ LA)</div>', unsafe_allow_html=True)
    with col_btn:
        if st.button("🔄 마스터 스케줄 갱신", help="클릭 시 선사 사이트에서 최신 스케줄을 수집합니다."):
            with st.spinner("스크래퍼 실행 중... (약 10~30초 소요)"):
                import subprocess
                script_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(script_dir)
                scraper_path = os.path.join(project_root, "scrapers", "scheduler_main.py")
                
                try:
                    subprocess.run(["python", scraper_path], check=True, capture_output=True)
                    st.success("갱신 완료!")
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.error(f"스크래핑 실패: {e.stderr.decode('utf-8', errors='ignore')}")
    
    if master_df is None or inventory_df is None or shipping_df is None or shipping_df.empty:
        st.info("데이터가 충분하지 않아 시뮬레이션을 실행할 수 없습니다. 데이터를 먼저 불러와 주세요.")
        return
        
    st.markdown("""
    <div class="info-box">
    <strong>💡 미국 창고(CGETC) 선적 일정 추천</strong><br>
    미국 창고의 상품별 <strong>예상 소진일</strong>을 기반으로, 재고 부족 사태를 방지하기 위해 
    미리 예약해야 하는 <strong>추천 선적 스케줄(Recommended Vessel)</strong>을 안내합니다.<br>
    해양수산부 데이터를 통해 <strong>실제 출항 예정 선박</strong>을 매칭합니다.
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
        
    # 입고 예정 수량(Transfers) 반영
    try:
        from data.supabase_client import fetch_transfers
        transfers_df = fetch_transfers()
        if not transfers_df.empty:
            in_transit_df = transfers_df[
                transfers_df["도착지"].astype(str).str.contains("CGETC", na=False) &
                ~transfers_df["상태"].astype(str).str.replace(" ", "").str.contains("입고완료|완료", na=False)
            ]
            if not in_transit_df.empty:
                in_transit_agg = in_transit_df.groupby("상품코드")["선적수량"].sum().reset_index()
                in_transit_agg.rename(columns={"선적수량": "입고예정수량"}, inplace=True)
                
                # us_inv에 입고예정수량 합산
                us_inv = us_inv.merge(in_transit_agg, on="상품코드", how="left")
                us_inv["현재고"] = us_inv["현재고"] + us_inv["입고예정수량"].fillna(0)
    except Exception as e:
        print(f"입고 예정 수량 반영 중 오류: {e}")

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
    
    # 3. 스케줄 로드
    schedules_df = fetch_schedules(today.strftime("%Y-%m-%d"), port_name=selected_port_name)
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
                
                in_transit = row.get("입고예정수량", 0)
                if pd.isna(in_transit):
                    in_transit = 0
                    
                if in_transit > 0:
                    real_stock = row['현재고'] - in_transit
                    st.write(f"- **현재고**: {row['현재고']:,.0f}개  \n  <span style='font-size: 0.85em; color: gray;'>(실재고 {real_stock:,.0f}개 + 입고예정 {in_transit:,.0f}개 반영)</span>", unsafe_allow_html=True)
                else:
                    st.write(f"- **현재고**: {row['현재고']:,.0f}개")
                    
                st.write(f"- **예상 소진일**: **<span style='color:#d32f2f;'>{row['예상소진일']}</span>**", unsafe_allow_html=True)
                st.write(f"- **필요 입항일(Port ETA)**: {target_port_eta.strftime('%Y-%m-%d')} 이전")
                
            with c2:
                days_to_expiry = (expiry_date.date() - today).days
                if days_to_expiry >= 90:
                    st.info(f"💡 **선적 추천 보류 (여유)**  \n예상 소진일까지 **{days_to_expiry}일**이 남아 아직 선적 추천 대상이 아닙니다. 추후 다시 확인해 주세요.")
                elif possible_vessels.empty:
                    st.error(f"🚨 **추천 가능한 선적 스케줄이 없습니다!**  \n창고 입고를 위해 늦어도 **{target_port_eta.strftime('%Y-%m-%d')}** 까지는 항구에 도착(ETA)해야 하지만, 해상 운송으로는 기한을 맞출 수 없습니다. **항공 운송(Air Freight)**을 고려하세요.")
                else:
                    recommended = possible_vessels.iloc[-1]
                    carrier = recommended.get('선적사', '')
                    badge = f" `{carrier}`" if carrier else ""
                    st.success(f"✅ **추천 선적 (Recommended Vessel): {recommended['Vessel']}**{badge}")
                    st.write(f"⏰ **화물 반입 마감(Cargo Cut-off)**: {recommended['Cut-off (화물 반입 마감)']}")
                    st.write(f"🚢 **ETD({selected_port_name} 출항)**: {recommended['ETD (출항)']}")
                    st.write(f"🛬 **ETA(LA 항구 입항)**: {recommended['ETA (LA 입항)']}")
                    
            st.divider()
            st.divider()
            
    # 전체 선적 스케줄 렌더링 (부산항, 인천항 모두 고정 노출)
    busan_schedules_df = fetch_schedules(today.strftime("%Y-%m-%d"), port_name="부산항")
    icn_schedules_df = fetch_schedules(today.strftime("%Y-%m-%d"), port_name="인천항")
    
    st.markdown("### 📅 전체 선적 스케줄 (부산항 ➔ LA)")
    if busan_schedules_df.empty:
        st.info("현재 공공데이터에 등록된 부산항 출항 스케줄이 없습니다.")
    else:
        st.dataframe(busan_schedules_df.drop(columns=["ETA_dt"], errors="ignore"), width="stretch", hide_index=True)
    
    st.markdown("### 📅 전체 선적 스케줄 (인천항 ➔ LA)")
    if icn_schedules_df.empty:
        st.info("현재 공공데이터에 등록된 인천항 출항 스케줄이 없습니다.")
    else:
        st.dataframe(icn_schedules_df.drop(columns=["ETA_dt"], errors="ignore"), width="stretch", hide_index=True)
