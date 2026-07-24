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


def simulate_inventory_events(master_df, inventory_df, shipping_df, po_df, transfer_df, 
                              us_lead_time=30, kr_lead_time=45, sim_days=90, velocity_days=90,
                              show_in_out_events=True, target_order_days=90, moq_sticks=1000000):
    velocity_df = calculate_daily_velocity(shipping_df, days=velocity_days)
    
    kr_inv = {}
    us_inv = {}
    if inventory_df is not None and not inventory_df.empty:
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
    cat_col = "품목구분" if "품목구분" in master_df.columns else "구분"
    
    products_info = {}
    cats_dict = {}
    
    for _, row in master_df.drop_duplicates(subset=["상품코드"]).iterrows():
        c = row["상품코드"]
        name = row["상품명"]
        cat = str(row.get(cat_col, "기타"))
        sticks = int(pd.to_numeric(row.get("내포입", 1), errors='coerce'))
        if sticks <= 0: sticks = 1
        
        kr_stock = float(kr_inv.get(c, 0.0))
        us_stock = float(us_inv.get(c, 0.0))
        
        kr_v = 0.0
        us_v = 0.0
        v_match = velocity_df[velocity_df["상품코드"] == c]
        if not v_match.empty:
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

        products_info[c] = {
            "name": name,
            "cat": cat,
            "sticks": sticks,
            "kr_stock": kr_stock,
            "us_stock": us_stock,
            "kr_v": kr_v,
            "us_v": us_v,
            "po_events": po_events,
            "tr_in": tr_in,
            "tr_out": tr_out,
            "us_is_out": False,
            "us_out_start": None,
            "kr_is_out": False,
            "kr_out_start": None
        }
        
        if cat not in cats_dict:
            cats_dict[cat] = []
        cats_dict[cat].append(c)

    # 초기 확정된 입출고 이벤트를 캘린더에 표시
    for c, info in products_info.items():
        name = info["name"]
        if show_in_out_events:
            for d, qty in info["po_events"].items():
                if d >= today: add_event(d, "PO_IN", name, f"📦 한국 입고 (+{qty:,.0f})")
            for d, qty in info["tr_out"].items():
                if d >= today: add_event(d, "TR_OUT", name, f"🚢 미국행 출항 (-{qty:,.0f})")
            for d, qty in info["tr_in"].items():
                if d >= today: add_event(d, "TR_IN", name, f"🇺🇸 미국 입고 (+{qty:,.0f})")

    # 카테고리 단위로 날짜별 연쇄 시뮬레이션
    for cat, codes in cats_dict.items():
        sorted_codes = sorted(codes, key=lambda x: (products_info[x]["sticks"], products_info[x]["kr_v"]), reverse=True)
        main_code = sorted_codes[0] if sorted_codes else None
        
        for day_offset in range(sim_days):
            current_date = today + timedelta(days=day_offset)
            needs_po_group = False
            
            for c in codes:
                info = products_info[c]
                
                # Apply daily events
                if current_date in info["po_events"]: info["kr_stock"] += info["po_events"][current_date]
                if current_date in info["tr_out"]: info["kr_stock"] -= info["tr_out"][current_date]
                if current_date in info["tr_in"]: info["us_stock"] += info["tr_in"][current_date]
                
                # Apply daily burn
                info["kr_stock"] -= info["kr_v"]
                info["us_stock"] -= info["us_v"]
                
                # ---------------- US Stock Out Handling (Individual) ----------------
                if info["us_stock"] < 0:
                    if not info["us_is_out"]:
                        info["us_is_out"] = True
                        info["us_out_start"] = current_date
                        
                    future_tr_in = sum(qty for d, qty in info["tr_in"].items() if d > current_date)
                    if info["us_stock"] + future_tr_in <= 0 and info["us_v"] > 0:
                        transfer_qty = math.ceil(info["us_v"] * target_order_days)
                        if transfer_qty > 0:
                            req_date = current_date - timedelta(days=us_lead_time)
                            if req_date < today:
                                add_event(today, "TRANSFER_REQ", info["name"], f"🚨 긴급 선적 (추천 {transfer_qty:,.0f}개 / 소진 {current_date.strftime('%m/%d')})")
                                req_date = today
                            else:
                                add_event(req_date, "TRANSFER_REQ", info["name"], f"🚢 선적 필요 (추천 {transfer_qty:,.0f}개 / 소진 {current_date.strftime('%m/%d')})")
                            
                            arrival_date = req_date + timedelta(days=us_lead_time)
                            if arrival_date not in info["tr_in"]: info["tr_in"][arrival_date] = 0
                            info["tr_in"][arrival_date] += transfer_qty
                            
                            if req_date <= current_date: info["kr_stock"] -= transfer_qty
                            if arrival_date <= current_date: info["us_stock"] += transfer_qty
                else:
                    if info["us_is_out"]:
                        info["us_is_out"] = False
                        duration = (current_date - info["us_out_start"]).days
                        add_event(info["us_out_start"], "US_OUT", info["name"], f"🇺🇸 {duration}일 품절예정 ({current_date.strftime('%m/%d')} 회복)")
                
                # ---------------- KR Stock Out Handling (Grouped by Category) ----------------
                if c == main_code and info["kr_stock"] < 0:
                    if not info["kr_is_out"]:
                        info["kr_is_out"] = True
                        info["kr_out_start"] = current_date
                        
                    future_kr = sum(qty for d, qty in info["po_events"].items() if d > current_date)
                    if info["kr_stock"] + future_kr <= 0 and info["kr_v"] > 0:
                        needs_po_group = True
                elif c != main_code and info["kr_stock"] < 0:
                    # 부속품(체험키트 등)의 품절 추적 처리
                    if not info["kr_is_out"]:
                        info["kr_is_out"] = True
                        info["kr_out_start"] = current_date
                
                if info["kr_stock"] >= 0 and info["kr_is_out"]:
                    info["kr_is_out"] = False
                    duration = (current_date - info["kr_out_start"]).days
                    add_event(info["kr_out_start"], "KR_OUT", info["name"], f"🇰🇷 {duration}일 품절예정 ({current_date.strftime('%m/%d')} 회복)")

            # ---------------- Category Group PO Trigger ----------------
            if needs_po_group:
                total_sticks_ordered = 0
                temp_orders = {}
                
                for c in codes:
                    info = products_info[c]
                    demand_boxes = math.ceil(info["kr_v"] * target_order_days)
                    if demand_boxes < 0: demand_boxes = 0
                    temp_orders[c] = demand_boxes
                    total_sticks_ordered += (demand_boxes * info["sticks"])
                
                if total_sticks_ordered < moq_sticks and total_sticks_ordered > 0:
                    shortfall_sticks = moq_sticks - total_sticks_ordered
                    main_sticks = products_info[main_code]["sticks"]
                    added_boxes = math.ceil(shortfall_sticks / main_sticks)
                    temp_orders[main_code] += added_boxes
                    
                for c, qty_boxes in temp_orders.items():
                    if qty_boxes > 0:
                        info = products_info[c]
                        req_date = current_date - timedelta(days=kr_lead_time)
                        if req_date < today:
                            add_event(today, "PO_REQ", info["name"], f"🚨 긴급 발주 (추천 {qty_boxes:,.0f}개 / 소진 {current_date.strftime('%m/%d')})")
                            req_date = today
                        else:
                            add_event(req_date, "PO_REQ", info["name"], f"📦 발주 필요 (추천 {qty_boxes:,.0f}개 / 소진 {current_date.strftime('%m/%d')})")
                            
                        arrival_date = req_date + timedelta(days=kr_lead_time)
                        if arrival_date not in info["po_events"]:
                            info["po_events"][arrival_date] = 0
                        info["po_events"][arrival_date] += qty_boxes
                        
                        if arrival_date <= current_date:
                            info["kr_stock"] += qty_boxes

        # 시뮬레이션 종료 후 아직 회복되지 못한 품절 이벤트 마감 처리
        for c in codes:
            info = products_info[c]
            if info["us_is_out"]:
                add_event(info["us_out_start"], "US_OUT", info["name"], "🇺🇸 미국 소진 (입고 미정)")
            if info["kr_is_out"]:
                add_event(info["kr_out_start"], "KR_OUT", info["name"], "🇰🇷 한국 소진 (입고 미정)")
                
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
        
    col_opt1, col_opt3 = st.columns(2)
    with col_opt1:
        show_in_out_events = st.checkbox("입고/출항 확정 이벤트도 캘린더에 표시하기", value=True)
    with col_opt3:
        target_order_days = st.number_input("발주/선적 권장량 (일치 출고량)", value=90, min_value=1, max_value=365, help="품절 시 발주 및 선적을 추천할 목표 일수")
        
    moq_sticks = st.number_input("카테고리별 1회 최소 발주량 (MOQ 스틱/포 기준)", min_value=0, max_value=10000000, value=1000000, step=50000, help="카테고리 내 상품들의 N일치 주문량이 부족할 경우 본품에 추가 발주를 진행합니다.")

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
        sim_days=365, velocity_days=velocity_days,
        show_in_out_events=show_in_out_events, target_order_days=target_order_days, moq_sticks=moq_sticks
    )
    
    today = date.today()
    
    # ---------------- UI: Calendar Rendering ----------------
    if "ml_cal_view_date" not in st.session_state:
        st.session_state["ml_cal_view_date"] = today.replace(day=1)
        
    curr_view = st.session_state["ml_cal_view_date"]
    
    all_months = []
    for i in range(13): 
        m = today.month + i
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        all_months.append(date(y, m, 1))
            
    options = [d.strftime("%Y년 %m월") for d in all_months]
    curr_str = curr_view.strftime("%Y년 %m월")
    
    if curr_str not in options:
        options.append(curr_str)
        options = sorted(options)
        
    curr_idx = options.index(curr_str)

    def change_month():
        selected_str = st.session_state.get("sel_ml_month_key")
        if selected_str:
            new_idx = options.index(selected_str)
            if new_idx < len(all_months):
                st.session_state["ml_cal_view_date"] = all_months[new_idx]

    def go_prev():
        v = st.session_state["ml_cal_view_date"]
        m, y = v.month - 1, v.year
        if m < 1: m, y = 12, y - 1
        new_date = date(y, m, 1)
        st.session_state["ml_cal_view_date"] = new_date
        st.session_state["sel_ml_month_key"] = new_date.strftime("%Y년 %m월")

    def go_next():
        v = st.session_state["ml_cal_view_date"]
        m, y = v.month + 1, v.year
        if m > 12: m, y = 1, y + 1
        new_date = date(y, m, 1)
        st.session_state["ml_cal_view_date"] = new_date
        st.session_state["sel_ml_month_key"] = new_date.strftime("%Y년 %m월")

    _, col_btn1, col_sel2, col_btn2, _ = st.columns([3, 1, 2, 1, 3])
    
    with col_btn1:
        st.button("◀ 이전 달", on_click=go_prev, key="btn_ml_prev", use_container_width=True)
        
    with col_sel2:
        st.selectbox(
            "조회 월 선택", 
            options, 
            index=curr_idx, 
            key="sel_ml_month_key",
            on_change=change_month,
            label_visibility="collapsed"
        )

    with col_btn2:
        st.button("다음 달 ▶", on_click=go_next, key="btn_ml_next", use_container_width=True)
                
    st.markdown("""
        <style>
        .calendar-container { margin-top: 20px; overflow-x: auto; }
        .month-title { font-size: 1.2rem; font-weight: 600; margin-bottom: 10px; color: #1e293b; text-align: center; }
        </style>
    """, unsafe_allow_html=True)
    
    cal = MultiLevelCalendar(events_by_date, curr_view.year, curr_view.month)
    html_cal = cal.formatmonth(withyear=True)
    
    st.markdown(f'<div class="calendar-container"><div class="month-title">{curr_view.year}년 {curr_view.month}월</div>{html_cal}</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
