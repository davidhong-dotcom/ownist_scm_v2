import streamlit as st
import pandas as pd
import calendar
from datetime import date, timedelta
import math
import hashlib

def get_product_color(product_name):
    palette = [
        "#D32F2F", "#C2185B", "#7B1FA2", "#512DA8", "#303F9F", 
        "#1976D2", "#0288D1", "#0097A7", "#00796B", "#388E3C", 
        "#689F38", "#AFB42B", "#F57C00", "#E64A19", "#5D4037", 
        "#616161", "#455A64"
    ]
    hash_val = int(hashlib.md5(str(product_name).encode('utf-8')).hexdigest(), 16)
    return palette[hash_val % len(palette)]

class POCalendar(calendar.HTMLCalendar):
    def __init__(self, po_data, year, month):
        super().__init__()
        self.po_data = po_data
        self.year = year
        self.month = month

    def formatday(self, day, weekday):
        if day == 0:
            return '<td class="noday" style="background-color: #f9f9f9; border: 1px solid #ddd;">&nbsp;</td>'
        
        current_date = date(self.year, self.month, day)
        
        po_html = ""
        if current_date in self.po_data:
            for po in self.po_data[current_date]:
                # 입고완료면 회색, 아니면 상품명 기반 고유 색상
                is_done = "입고완료" in str(po['입고상태']).replace(" ", "")
                base_color = get_product_color(po["상품명"])
                bg_color = "#9e9e9e" if is_done else base_color
                text_dec = "line-through" if is_done else "none"
                opacity = "0.6" if is_done else "1.0"
                
                po_html += f'<div style="background-color: {bg_color}; color: white; padding: 4px 6px; margin-top: 4px; border-radius: 4px; font-size: 11px; text-decoration: {text_dec}; opacity: {opacity}; line-height: 1.3;"><b>{po["외주처"]}</b><br>{po["상품명"]}<br>수량: {po["발주수량"]:,}</div>'
        
        # 오늘 날짜 강조
        today = date.today()
        is_today = (current_date == today)
        day_style = "background-color: #e3f2fd; font-weight: bold; border-radius: 50%; width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center;" if is_today else ""
        
        return f'<td class="{self.cssclasses[weekday]}" style="padding: 8px; border: 1px solid #ddd; vertical-align: top; width: 14.28%; height: 120px;">' \
               f'<div style="text-align: right;"><span style="{day_style}">{day}</span></div>' \
               f'{po_html}' \
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
        return '' # 달력 상단에 스트림릿 UI로 월을 표시할 것이므로 내장 헤더는 숨김
        
    def formatweekheader(self):
        s = ''.join(f'<th style="padding: 10px; border: 1px solid #ddd; background-color: #f1f3f4; text-align: center;">{day}</th>' for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        return f'<tr>{s}</tr>'


def render_po_calendar(po_df: pd.DataFrame):
    if po_df is None or po_df.empty:
        st.info("표시할 발주 데이터가 없습니다.")
        return

    # 날짜 데이터가 있는 항목만 필터링
    valid_po = po_df.dropna(subset=['납기예정일']).copy()
    if valid_po.empty:
        st.info("납기예정일이 등록된 발주 건이 없습니다.")
        return

    # 날짜별로 그룹핑
    po_dict = {}
    for _, row in valid_po.iterrows():
        d = row['납기예정일']
        if pd.isna(d): continue
        if d not in po_dict:
            po_dict[d] = []
        po_dict[d].append({
            '외주처': row.get('외주처', '알수없음'),
            '상품명': row.get('상품명', '알수없음'),
            '발주수량': int(row.get('발주수량', 0)),
            '입고상태': row.get('입고상태', '대기')
        })

    # Streamlit UI
    st.markdown("### 📅 월별 발주 및 납기 달력")
    
    today = date.today()
    if "cal_view_date" not in st.session_state:
        st.session_state["cal_view_date"] = today.replace(day=1)
        
    curr_view = st.session_state["cal_view_date"]
    
    # 앞뒤 5년 범위 생성
    start_year = today.year - 5
    end_year = today.year + 5
    
    all_months = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            all_months.append(date(y, m, 1))
            
    options = [d.strftime("%Y년 %m월") for d in all_months]
    curr_str = curr_view.strftime("%Y년 %m월")
    
    if curr_str not in options:
        options.append(curr_str)
        options = sorted(options)
        
    curr_idx = options.index(curr_str)

    def go_prev():
        v = st.session_state["cal_view_date"]
        m, y = v.month - 1, v.year
        if m < 1: m, y = 12, y - 1
        st.session_state["cal_view_date"] = date(y, m, 1)

    def go_next():
        v = st.session_state["cal_view_date"]
        m, y = v.month + 1, v.year
        if m > 12: m, y = 1, y + 1
        st.session_state["cal_view_date"] = date(y, m, 1)

    _, col_btn1, col_sel, col_btn2, _ = st.columns([3, 1, 2, 1, 3])
    
    with col_btn1:
        st.button("◀ 이전 달", on_click=go_prev, use_container_width=True)
        
    with col_sel:
        selected_str = st.selectbox(
            "조회 월 선택", 
            options, 
            index=curr_idx, 
            label_visibility="collapsed"
        )
        if selected_str != curr_str:
            new_idx = options.index(selected_str)
            if new_idx < len(all_months):
                st.session_state["cal_view_date"] = all_months[new_idx]
                st.rerun()

    with col_btn2:
        st.button("다음 달 ▶", on_click=go_next, use_container_width=True)
                
    # 선택된 달력 렌더링
    cal = POCalendar(po_dict, curr_view.year, curr_view.month)
    html_calendar = cal.formatmonth()
    
    st.markdown(html_calendar, unsafe_allow_html=True)
