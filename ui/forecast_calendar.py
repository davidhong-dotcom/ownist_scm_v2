import streamlit as st
import pandas as pd
import math
import calendar
from datetime import date, timedelta
import hashlib
import numpy as np

def get_product_color(product_name):
    palette = [
        "#D32F2F", "#C2185B", "#7B1FA2", "#512DA8", "#303F9F", 
        "#1976D2", "#0288D1", "#0097A7", "#00796B", "#388E3C", 
        "#689F38", "#AFB42B", "#F57C00", "#E64A19", "#5D4037", 
        "#616161", "#455A64"
    ]
    hash_val = int(hashlib.md5(str(product_name).encode('utf-8')).hexdigest(), 16)
    return palette[hash_val % len(palette)]

class ForecastCalendar(calendar.HTMLCalendar):
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
                if ev['type'] == 'ORDER':
                    bg_color = "#E64A19" # 주황빛 (발주)
                    title = "발주 필요"
                else:
                    bg_color = "#1976D2" # 파란빛 (입고)
                    title = "예상 입고"
                
                ev_html += f'<div style="background-color: {bg_color}; color: white; padding: 4px 6px; margin-top: 4px; border-radius: 4px; font-size: 11px; line-height: 1.3;"><b>{title}</b><br>{ev["상품명"]}<br>수량: {ev["수량"]:,}</div>'
        
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
    if shipping_df is None or shipping_df.empty:
        return pd.DataFrame(columns=["상품코드", "일평균출고량"])
        
    cutoff_date = date.today() - timedelta(days=days)
    recent_ship = shipping_df[
        pd.to_datetime(shipping_df["출고일자"]).dt.date >= cutoff_date
    ]
    
    if recent_ship.empty:
        return pd.DataFrame(columns=["상품코드", "일평균출고량"])
        
    agg = recent_ship.groupby(["상품코드"])["출고수량"].sum().reset_index()
    agg["일평균출고량"] = agg["출고수량"] / days
    return agg[["상품코드", "일평균출고량"]]


def render_forecast_calendar(master_df: pd.DataFrame, inventory_df: pd.DataFrame, shipping_df: pd.DataFrame, po_df: pd.DataFrame):
    st.markdown('<div class="sec-title">🗓️ 발주 예측(Forecasting) 통합 캘린더</div>', unsafe_allow_html=True)
    st.info("전체 상품의 일평균 출고량 추세를 바탕으로, 품목구분(카테고리) 단위로 재고가 부족해지는 시점에 연쇄적인 복합 발주 시뮬레이션을 수행합니다.")
    
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        lead_time = st.number_input("발주 리드타임 (일)", min_value=1, max_value=180, value=45, step=1, help="발주서 전달 후 입고까지 걸리는 일수 (전체 상품 공통 적용)")
    with col_opt2:
        moq_sticks = st.number_input("카테고리별 1회 발주량 (MOQ 스틱/포 기준)", min_value=0, max_value=10000000, value=1000000, step=50000, help="카테고리 단위로 한 번 발주할 때 생산할 최소 수량(스틱 단위)")
        
    cat_col = "품목구분" if "품목구분" in master_df.columns else "구분"
    
    # S&OP 대상 핵심 카테고리만 필터링
    target_categories = ["케라그로우", "트로피컬", "트리플샤인", "트리플콜라겐"]
    if cat_col in master_df.columns:
        master_df = master_df[master_df[cat_col].isin(target_categories)]
        categories = sorted([str(x) for x in master_df[cat_col].dropna().unique().tolist()])
    else:
        categories = []
    
    selected_cats = st.multiselect("조회할 품목구분 선택 (비워두면 전체 카테고리 시뮬레이션)", options=categories, default=[])
    
    # 1. 데이터 준비
    velocity_df = calculate_daily_velocity(shipping_df, days=90)
    
    # 기초 재고 매핑
    inv_map = {}
    if inventory_df is not None and not inventory_df.empty:
        inv_agg = inventory_df.groupby("상품코드")["현재고"].sum().to_dict()
        inv_map = inv_agg
        
    # 진행 중인 PO 매핑
    # 구조: po_map[product_code][date] = qty
    po_map = {}
    if po_df is not None and not po_df.empty:
        pending_po = po_df[~po_df["입고상태"].str.replace(" ", "").str.contains("입고완료", na=False)]
        for _, row in pending_po.iterrows():
            c = row["상품코드"]
            d = row["납기예정일"]
            if pd.isna(d) or pd.isna(c): continue
            if isinstance(d, str):
                try: d = pd.to_datetime(d).date()
                except: continue
            if c not in po_map: po_map[c] = {}
            if d not in po_map[c]: po_map[c][d] = 0
            po_map[c][d] += row["발주수량"]

    # 시뮬레이션을 위한 프로덕트 정보 구조화
    products_info = {}
    
    for _, row in master_df.drop_duplicates(subset=["상품코드"]).iterrows():
        c = row["상품코드"]
        cat = str(row.get(cat_col, "기타"))
        if cat == "nan" or not cat.strip(): cat = "기타"
        
        # 만약 멀티셀렉트로 선택한 카테고리가 있다면 필터링 (선택 안했으면 전부 포함)
        if selected_cats and cat not in selected_cats:
            continue
            
        name = row["상품명"]
        sticks_per_box = int(pd.to_numeric(row.get("내포입", 1), errors='coerce'))
        if sticks_per_box <= 0: sticks_per_box = 1
        
        daily_burn = 0.0
        v_match = velocity_df[velocity_df["상품코드"] == c]
        if not v_match.empty: daily_burn = v_match["일평균출고량"].iloc[0]
        
        products_info[c] = {
            "name": name,
            "cat": cat,
            "sticks": sticks_per_box,
            "burn": daily_burn,
            "stock": float(inv_map.get(c, 0)),
            "pending": po_map.get(c, {}).copy()
        }
        
    # 카테고리별로 상품들 묶기
    cats_dict = {}
    for c, info in products_info.items():
        cat = info["cat"]
        if cat not in cats_dict:
            cats_dict[cat] = []
        cats_dict[cat].append(c)

    # 365일 시뮬레이션
    sim_days = 365
    today = date.today()
    
    events_by_date = {}
    forecast_events = []
    
    def add_event(d, type_str, product_name, qty):
        if d not in events_by_date:
            events_by_date[d] = []
        events_by_date[d].append({
            "type": type_str,
            "상품명": product_name,
            "수량": qty
        })
        forecast_events.append({
            "날짜": d,
            "종류": "발주서 전달" if type_str == "ORDER" else "예상 입고",
            "상품명": product_name,
            "수량": qty
        })

    # 초기 확정된 입고 이벤트를 캘린더에 추가
    for c, info in products_info.items():
        for d, qty in info["pending"].items():
            add_event(d, "ARRIVAL", info["name"], qty)

    # 카테고리별 독립적 시뮬레이션 루프
    for cat, codes in cats_dict.items():
        # 이 카테고리의 대표 상품(본품) 찾기 (내포입이 가장 크고, 출고량이 많은 것)
        sorted_codes = sorted(codes, key=lambda x: (products_info[x]["sticks"], products_info[x]["burn"]), reverse=True)
        main_code = sorted_codes[0]
        
        for i in range(sim_days):
            curr_date = today + timedelta(days=i)
            
            needs_order = False
            
            # 매일 재고 업데이트 및 메인 상품 체크
            for c in codes:
                info = products_info[c]
                # 도착한 물량 더하기
                if curr_date in info["pending"]:
                    info["stock"] += info["pending"][curr_date]
                # 일일 소진량 빼기
                info["stock"] -= info["burn"]
                
                # 본품(main_code) 기준으로만 발주 트리거를 판단 (체험키트 품절로 인한 조기 발주 방지)
                if c == main_code:
                    safety_threshold = info["burn"] * lead_time
                    if info["stock"] <= safety_threshold and info["burn"] > 0:
                        # 미래에 들어올 예정인 발주잔량 합산
                        future_arrivals = sum([qty for d, qty in info["pending"].items() if d > curr_date])
                        if (info["stock"] + future_arrivals) <= safety_threshold:
                            needs_order = True
            
            # 하나라도 발주가 필요하면 카테고리 전체 발주 트리거
            if needs_order:
                # 1. 각 상품별로 90일치 수요량 산출
                total_sticks_ordered = 0
                temp_orders = {}
                
                for c in codes:
                    info = products_info[c]
                    # 해당 상품의 90일치 출고량
                    demand_90d_boxes = math.ceil(info["burn"] * 90)
                    if demand_90d_boxes < 0: demand_90d_boxes = 0
                    
                    temp_orders[c] = demand_90d_boxes
                    total_sticks_ordered += (demand_90d_boxes * info["sticks"])
                
                # 2. MOQ 보정 (전체 스틱 수가 moq_sticks 보다 작으면 대표 본품에 부족분 추가)
                if total_sticks_ordered < moq_sticks and total_sticks_ordered > 0:
                    shortfall_sticks = moq_sticks - total_sticks_ordered
                    main_sticks_per_box = products_info[main_code]["sticks"]
                    added_boxes = math.ceil(shortfall_sticks / main_sticks_per_box)
                    temp_orders[main_code] += added_boxes
                    
                # 3. 발주 확정 및 이벤트 등록
                order_date = curr_date
                arrival_date = curr_date + timedelta(days=lead_time)
                
                for c, qty_boxes in temp_orders.items():
                    if qty_boxes > 0:
                        info = products_info[c]
                        # 캘린더 등록
                        add_event(order_date, "ORDER", info["name"], qty_boxes)
                        add_event(arrival_date, "ARRIVAL", info["name"], qty_boxes)
                        
                        # 가상 잔량에 업데이트 (미래 입고)
                        if arrival_date not in info["pending"]:
                            info["pending"][arrival_date] = 0
                        info["pending"][arrival_date] += qty_boxes

    # ---------------- UI: Total Aggregation ----------------
    total_orders_boxes = 0
    total_sticks = 0
    for ev in forecast_events:
        if ev["종류"] == "발주서 전달":
            total_orders_boxes += ev["수량"]
            # 역산해서 스틱 수량 찾기
            p_name = ev["상품명"]
            sticks = 1
            for info in products_info.values():
                if info["name"] == p_name:
                    sticks = info["sticks"]
                    break
            total_sticks += (ev["수량"] * sticks)
    
    col_sum1, col_sum2 = st.columns(2)
    with col_sum1:
        st.metric("📦 향후 1년간 가상 총 발주 필요량 (완제품 합산)", f"{total_orders_boxes:,.0f} 개")
    with col_sum2:
        st.metric("🧪 향후 1년간 사급원료 필요 추산 (스틱 합산)", f"{total_sticks:,.0f} 포")
        
    st.divider()
    
    # ---------------- UI: Calendar Rendering ----------------
    if "fc_cal_view_date" not in st.session_state:
        st.session_state["fc_cal_view_date"] = today.replace(day=1)
        
    curr_view = st.session_state["fc_cal_view_date"]
    
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
        selected_str = st.session_state.get("sel_fc_month_key")
        if selected_str:
            new_idx = options.index(selected_str)
            if new_idx < len(all_months):
                st.session_state["fc_cal_view_date"] = all_months[new_idx]

    def go_prev():
        v = st.session_state["fc_cal_view_date"]
        m, y = v.month - 1, v.year
        if m < 1: m, y = 12, y - 1
        new_date = date(y, m, 1)
        st.session_state["fc_cal_view_date"] = new_date
        st.session_state["sel_fc_month_key"] = new_date.strftime("%Y년 %m월")

    def go_next():
        v = st.session_state["fc_cal_view_date"]
        m, y = v.month + 1, v.year
        if m > 12: m, y = 1, y + 1
        new_date = date(y, m, 1)
        st.session_state["fc_cal_view_date"] = new_date
        st.session_state["sel_fc_month_key"] = new_date.strftime("%Y년 %m월")

    _, col_btn1, col_sel2, col_btn2, _ = st.columns([3, 1, 2, 1, 3])
    
    with col_btn1:
        st.button("◀ 이전 달", on_click=go_prev, key="btn_fc_prev", use_container_width=True)
        
    with col_sel2:
        st.selectbox(
            "조회 월 선택", 
            options, 
            index=curr_idx, 
            key="sel_fc_month_key",
            on_change=change_month,
            label_visibility="collapsed"
        )

    with col_btn2:
        st.button("다음 달 ▶", on_click=go_next, key="btn_fc_next", use_container_width=True)
                
    cal = ForecastCalendar(events_by_date, curr_view.year, curr_view.month)
    html_calendar = cal.formatmonth()
    
    st.markdown(html_calendar, unsafe_allow_html=True)
    
    with st.expander("📝 시뮬레이션 상세 내역 표 보기"):
        if forecast_events:
            df_ev = pd.DataFrame(forecast_events).sort_values("날짜")
            df_ev["날짜"] = df_ev["날짜"].astype(str)
            st.dataframe(df_ev.style.format({"수량": "{:,.0f}"}), use_container_width=True)
        else:
            st.info("예측된 발주 일정이 없습니다.")
