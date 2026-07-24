import streamlit as st
import pandas as pd
import math
import calendar
from datetime import date, timedelta
import hashlib

class MultiLevelCalendar(calendar.HTMLCalendar):
    def __init__(self, events_data, year, month):
        super().__init__()
        self.events_data = events_data
        self.year = year
        self.month = month

    def formatday(self, day, weekday):
        if day == 0:
            return '<td class="noday" style="background-color: #f9f9f9; border: 1px solid #ddd;">&nbsp;</td>'
        
        current_date = date(self.year, self.month, day)
        
        ev_html = ""
        if current_date in self.events_data:
            for ev in self.events_data[current_date]:
                type_str = ev['type']
                
                # 색상 매핑
                bg_color = "#999999"
                if type_str == "PO_REQ": bg_color = "#E64A19" # 진한 주황
                elif type_str == "TRANSFER_REQ": bg_color = "#F57C00" # 주황
                elif type_str == "KR_OUT": bg_color = "#C2185B" # 핑크레드
                elif type_str == "US_OUT": bg_color = "#D32F2F" # 레드
                elif type_str == "PO_IN": bg_color = "#1976D2" # 파랑
                elif type_str == "TR_OUT": bg_color = "#0288D1" # 밝은 파랑
                elif type_str == "TR_IN": bg_color = "#0097A7" # 청록
                
                ev_html += f'<div style="background-color: {bg_color}; color: white; padding: 4px 6px; margin-top: 4px; border-radius: 4px; font-size: 11px; line-height: 1.3;"><b>{ev["텍스트"]}</b><br>{ev["상품명"]}</div>'
        
        today = date.today()
        is_today = (current_date == today)
        day_style = "background-color: #e3f2fd; font-weight: bold; border-radius: 50%; width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center;" if is_today else ""
        
        return f'<td class="{self.cssclasses[weekday]}" style="padding: 8px; border: 1px solid #ddd; vertical-align: top; width: 14.28%; height: 120px; max-width: 14.28%; overflow-x: hidden;">' \
               f'<div style="text-align: right;"><span style="{day_style}">{day}</span></div>' \
               f'{ev_html}' \
               f'</td>'

    def formatmonth(self, withyear=True):
        v = []
        a = v.append
        a('<table border="0" cellpadding="0" cellspacing="0" class="month" style="width: 100%; border-collapse: collapse; font-family: sans-serif; table-layout: fixed;">')
        a(self.formatmonthname(self.year, self.month, withyear=withyear))
        a(self.formatweekheader())
        for week in self.monthdays2calendar(self.year, self.month):
            a(self.formatweek(week))
        a('</table>')
        return ''.join(v)
        
    def formatmonthname(self, theyear, themonth, withyear=True):
        return ''
        
    def formatweekheader(self):
        s = ''.join(f'<th style="padding: 10px; border: 1px solid #ddd; background-color: #f1f3f4; text-align: center;">{day}</th>' for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        return f'<tr>{s}</tr>'


def calculate_daily_velocity(shipping_df: pd.DataFrame, days: int = 90) -> pd.DataFrame:
    """채널별, 상품별 일평균 출고량 계산"""
    if shipping_df is None or shipping_df.empty:
        return pd.DataFrame(columns=["채널", "상품코드", "일평균출고량"])
        
    cutoff_date = date.today() - timedelta(days=days)
    recent_ship = shipping_df[
        pd.to_datetime(shipping_df["출고일자"]).dt.date >= cutoff_date
    ]
    
    if recent_ship.empty:
        return pd.DataFrame(columns=["채널", "상품코드", "일평균출고량"])
        
    agg = recent_ship.groupby(["채널", "상품코드"])["출고수량"].sum().reset_index()
    agg["일평균출고량"] = agg["출고수량"] / days
    return agg[["채널", "상품코드", "일평균출고량"]]


def simulate_inventory_events(master_df, inventory_df, shipping_df, po_df, transfer_df, us_lead_time, kr_lead_time, sim_days, velocity_days, show_in_out_events):
    velocity_df = calculate_daily_velocity(shipping_df, days=velocity_days)
    
    kr_inv = {}
    us_inv = {}
    if inventory_df is not None and not inventory_df.empty:
        # CGETC는 미국, 그 외의 모든 채널은 한국으로 간주하여 재고 합산
        us_df = inventory_df[inventory_df["채널"] == "CGETC"]
        kr_df = inventory_df[inventory_df["채널"] != "CGETC"]
        
        kr_inv = kr_df.groupby("상품코드")["현재고"].sum().to_dict()
        us_inv = us_df.groupby("상품코드")["현재고"].sum().to_dict()

    events_by_date = {}
    
    def add_event(d, type_str, product_name, text):
        if d not in events_by_date:
            events_by_date[d] = []
        events_by_date[d].append({
            "type": type_str,
            "상품명": product_name,
            "텍스트": text
        })
        
    today = date.today()
    
    for _, row in master_df.drop_duplicates(subset=["상품코드"]).iterrows():
        c = row["상품코드"]
        name = row["상품명"]
        
        kr_stock = float(kr_inv.get(c, 0.0))
        us_stock = float(us_inv.get(c, 0.0))
        
        kr_v = 0.0
        us_v = 0.0
        
        v_match = velocity_df[velocity_df["상품코드"] == c]
        if not v_match.empty:
            # CGETC는 미국 판매량, 그 외 모든 채널의 판매량은 한국 판매량으로 합산
            us_v = float(v_match[v_match["채널"] == "CGETC"]["일평균출고량"].sum())
            kr_v = float(v_match[v_match["채널"] != "CGETC"]["일평균출고량"].sum())
            
        po_events = {}
        if po_df is not None and not po_df.empty:
            po_sub = po_df[(po_df["상품코드"] == c) & (~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False))]
            for _, pr in po_sub.iterrows():
                d = pr["납기예정일"]
                if pd.notna(d):
                    if isinstance(d, str): 
                        try: d = pd.to_datetime(d).date()
                        except: continue
                    elif isinstance(d, pd.Timestamp): d = d.date()
                    if d not in po_events: po_events[d] = 0
                    po_events[d] += pr["발주수량"]
                    
        tr_out = {}
        tr_in = {}
        if transfer_df is not None and not transfer_df.empty:
            tr_sub = transfer_df[(transfer_df["상품코드"] == c) & (~transfer_df["상태"].str.replace(" ", "").str.contains("입고완료|완료", na=False))]
            for _, tr in tr_sub.iterrows():
                d_out = tr["선적일"]
                d_in = tr["하차예정일"]
                qty = tr.get("선적수량", 0)
                if pd.notna(d_out):
                    if isinstance(d_out, str): 
                        try: d_out = pd.to_datetime(d_out).date()
                        except: pass
                    elif isinstance(d_out, pd.Timestamp): d_out = d_out.date()
                    
                    if isinstance(d_out, date):
                        if d_out not in tr_out: tr_out[d_out] = 0
                        tr_out[d_out] += qty
                if pd.notna(d_in):
                    if isinstance(d_in, str): 
                        try: d_in = pd.to_datetime(d_in).date()
                        except: pass
                    elif isinstance(d_in, pd.Timestamp): d_in = d_in.date()
                    
                    if isinstance(d_in, date):
                        if d_in not in tr_in: tr_in[d_in] = 0
                        tr_in[d_in] += qty

        # 시뮬레이션을 배열로 먼저 진행하여 구간을 찾습니다.
        kr_history = []
        us_history = []
        
        kr_cur = kr_stock
        us_cur = us_stock
        
        for day_offset in range(sim_days):
            current_date = today + timedelta(days=day_offset)
            
            # Apply events for the day
            if current_date in po_events:
                kr_cur += po_events[current_date]
                if show_in_out_events:
                    add_event(current_date, "PO_IN", name, f"📦 한국 입고 (+{po_events[current_date]:,.0f})")
            if current_date in tr_out:
                kr_cur -= tr_out[current_date]
                if show_in_out_events:
                    add_event(current_date, "TR_OUT", name, f"🚢 미국행 출항 (-{tr_out[current_date]:,.0f})")
            if current_date in tr_in:
                us_cur += tr_in[current_date]
                if show_in_out_events:
                    add_event(current_date, "TR_IN", name, f"🇺🇸 미국 입고 (+{tr_in[current_date]:,.0f})")
                
            kr_cur -= kr_v
            us_cur -= us_v
            
            kr_history.append(kr_cur)
            us_history.append(us_cur)
            
        # 구간 탐색 함수
        def find_stockout_periods(history):
            periods = []
            in_out = False
            start = 0
            for i, stock in enumerate(history):
                if stock < 0 and not in_out:
                    in_out = True
                    start = i
                elif stock >= 0 and in_out:
                    in_out = False
                    periods.append((start, i))
            if in_out:
                periods.append((start, None))
            return periods
            
        kr_periods = find_stockout_periods(kr_history)
        us_periods = find_stockout_periods(us_history)
        
        # 미국 이벤트 생성
        for p_start, p_end in us_periods:
            if us_v <= 0: continue # 판매가 없으면 무시
            s_date = today + timedelta(days=p_start)
            if p_end is not None:
                e_date = today + timedelta(days=p_end)
                duration = p_end - p_start
                add_event(s_date, "US_OUT", name, f"🇺🇸 {duration}일 품절예정 ({e_date.strftime('%m/%d')} 회복)")
            else:
                add_event(s_date, "US_OUT", name, "🇺🇸 미국 소진 (입고 미정)")
                req_date = s_date - timedelta(days=us_lead_time)
                if req_date < today:
                    add_event(today, "TRANSFER_REQ", name, f"🚨 긴급 선적 (소진: {s_date.strftime('%m/%d')})")
                else:
                    add_event(req_date, "TRANSFER_REQ", name, f"🚢 선적 필요 (소진: {s_date.strftime('%m/%d')})")

        # 한국 이벤트 생성
        for p_start, p_end in kr_periods:
            if kr_v <= 0: continue
            s_date = today + timedelta(days=p_start)
            if p_end is not None:
                e_date = today + timedelta(days=p_end)
                duration = p_end - p_start
                add_event(s_date, "KR_OUT", name, f"🇰🇷 {duration}일 품절예정 ({e_date.strftime('%m/%d')} 회복)")
            else:
                add_event(s_date, "KR_OUT", name, "🇰🇷 한국 소진 (입고 미정)")
                req_date = s_date - timedelta(days=kr_lead_time)
                if req_date < today:
                    add_event(today, "PO_REQ", name, f"🚨 긴급 발주 (소진: {s_date.strftime('%m/%d')})")
                else:
                    add_event(req_date, "PO_REQ", name, f"📦 발주 필요 (소진: {s_date.strftime('%m/%d')})")
                
    return events_by_date


def render_multi_level_calendar(master_df, inventory_df, shipping_df, po_df, transfer_df):
    st.markdown('<div class="sec-title">🗓️ 다단계 예상재고 캘린더</div>', unsafe_allow_html=True)
    st.info("개별 상품의 한국(CK로지스) 및 미국(CGETC) 재고를 일별로 시뮬레이션하여 소진 시점과 발주/선적 필요 시점을 캘린더에 통합 표시합니다.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        kr_lead_time = st.number_input("공장 ➔ 한국 입고 리드타임 (일)", min_value=1, max_value=180, value=45, step=1, help="공장 발주부터 한국 창고 입고까지 소요되는 기간")
    with col2:
        us_lead_time = st.number_input("한국 ➔ 미국 입고 리드타임 (일)", min_value=1, max_value=180, value=30, step=1, help="한국 선적부터 미국 창고 입고까지 소요되는 기간")
    with col3:
        velocity_days = st.slider("평균 출고량 산출 기준 (최근 N일)", 7, 180, 90, help="해당 기간의 일평균 출고량을 미래 소진 예측에 사용")
        
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        show_in_out_events = st.checkbox("입고/출항 확정 이벤트도 캘린더에 표시하기", value=True)
    with col_opt2:
        sim_months = st.slider("달력 표시 기간 (개월)", 1, 12, 3)

    st.markdown("##### 📌 분석 대상 채널 필터")
    all_channels = set()
    if inventory_df is not None and not inventory_df.empty and "채널" in inventory_df.columns:
        all_channels.update(inventory_df["채널"].dropna().unique().tolist())
    if shipping_df is not None and not shipping_df.empty and "채널" in shipping_df.columns:
        all_channels.update(shipping_df["채널"].dropna().unique().tolist())
    
    all_channels = sorted(list(all_channels))
    selected_channels = []
    
    if all_channels:
        num_cols = min(len(all_channels), 5)
        if num_cols == 0: num_cols = 1
        cols = st.columns(num_cols)
        for i, ch in enumerate(all_channels):
            default_val = ("CK로지스" in ch) or ("CGETC" in ch)
            with cols[i % num_cols]:
                if st.checkbox(ch, value=default_val, key=f"ch_chk_{ch}"):
                    selected_channels.append(ch)

    # 선택된 채널만 필터링
    filtered_inventory = inventory_df
    filtered_shipping = shipping_df
    
    if inventory_df is not None and not inventory_df.empty and all_channels:
        filtered_inventory = inventory_df[inventory_df["채널"].isin(selected_channels)]
    if shipping_df is not None and not shipping_df.empty and all_channels:
        filtered_shipping = shipping_df[shipping_df["채널"].isin(selected_channels)]

    events_by_date = simulate_inventory_events(
        master_df, filtered_inventory, filtered_shipping, po_df, transfer_df,
        us_lead_time=us_lead_time, kr_lead_time=kr_lead_time,
        sim_days=sim_months*30, velocity_days=velocity_days,
        show_in_out_events=show_in_out_events
    )
    
    today = date.today()
    
    st.markdown("""
        <style>
        .calendar-container { margin-top: 20px; overflow-x: auto; }
        .month-title { font-size: 1.2rem; font-weight: 600; margin-bottom: 10px; color: #1e293b; text-align: center; }
        </style>
    """, unsafe_allow_html=True)
    
    for i in range(sim_months):
        target_date = today + timedelta(days=i*30)
        # 해당 월의 1일로 설정하여 달력을 그림 (첫 달은 이번 달)
        if i == 0:
            y, m = today.year, today.month
        else:
            m = today.month + i
            y = today.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            
        cal = MultiLevelCalendar(events_by_date, y, m)
        html_cal = cal.formatmonth(withyear=True)
        
        st.markdown(f'<div class="calendar-container"><div class="month-title">{y}년 {m}월</div>{html_cal}</div>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
