"""
ui/scm_documents.py
-------------------
SCM 전용 문서 자동화 모듈
사용자가 제공한 실제 실무 양식(발주서 PDF, 거래명세서 엑셀, PLT별 패킹리스트 엑셀)을
완벽하게 반영하여 웹 대시보드 인쇄 및 엑셀 다운로드로 구현.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
import io

# ────────────────────────────────────────────────
# 1. 엑셀 다운로드 유틸 함수
# ────────────────────────────────────────────────
def to_excel(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


# ────────────────────────────────────────────────
# 2. 발주서 작성 (Purchase Order Generator) - 실제 발주서 양식 100% 반영
# ────────────────────────────────────────────────
def render_po_generator(master_df: pd.DataFrame):
    st.markdown('<div class="sec-title">📝 발주서(Purchase Order) 작성</div>', unsafe_allow_html=True)
    st.info("💡 **실무 발주서 양식 적용 완료:** 공장(주식회사 서흥 등) 발주 양식에 맞춰 품목, 단가, 수량, 비고를 작성하고 A4 인쇄 및 엑셀 다운로드할 수 있습니다.")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        supplier_opt = st.selectbox("발주처 (공장/공급사)", ["주식회사 서흥", "코스맥스바이오(주)", "직접 입력"])
        if supplier_opt == "직접 입력":
            supplier = st.text_input("발주처명 직접 입력", value="OO공장(주)")
        else:
            supplier = supplier_opt
    with col2:
        po_num = st.text_input("발주 번호", value=f"PO-{date.today().strftime('%Y%m%d')}-01")
    with col3:
        order_date = st.date_input("발주 일자", value=date.today())
    with col4:
        delivery_date = st.date_input("납기 요청일", value=date.today() + timedelta(days=45))
        
    col_mgr, col_vat, col_curr, _ = st.columns([1, 1, 1, 1])
    with col_mgr:
        mgr_name = st.text_input("오니스트 담당자명", value="김재현")
    with col_vat:
        vat_type = st.selectbox("부가세(VAT) 적용", ["VAT 별도 (부가세불포)", "VAT 포함", "영세율 (0%)"])
    with col_curr:
        currency = st.selectbox("통화 단위", ["KRW (원)", "USD ($)"])

    st.markdown("##### 📌 발주 품목 및 수량 입력")
    st.caption("발주할 상품의 **'선택'** 체크박스를 켜고 **'수량'**, **'단가'**, **'비고'**(예: 14포입 / 본품 수량 변경 등)를 입력해 주세요.")
    
    # 마스터 기반 초기 표 생성
    df_init = master_df[["상품코드", "상품명", "내포입"]].drop_duplicates(subset=["상품코드"]).copy()
    df_init["선택"] = False
    df_init["수량"] = 0
    df_init["단가(부가세불포)"] = 0.0
    df_init["비고"] = ""
    
    # 대표 품목(트리플콜라겐 등) 기본 비고 예시 넣어두기
    for idx in df_init.index:
        p_name = str(df_init.loc[idx, "상품명"])
        sticks = df_init.loc[idx, "내포입"]
        if "콜라겐" in p_name:
            df_init.loc[idx, "비고"] = f"{int(sticks)}포입 / 본품 수량은 다른 SKU로 변경될 수 있음"
        else:
            df_init.loc[idx, "비고"] = f"{int(sticks)}포입"
    
    df_init = df_init[["선택", "상품코드", "상품명", "수량", "단가(부가세불포)", "비고"]]
    
    edited_df = st.data_editor(
        df_init,
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", default=False),
            "상품코드": st.column_config.TextColumn("상품코드", disabled=True),
            "상품명": st.column_config.TextColumn("제 품 명", disabled=True),
            "수량": st.column_config.NumberColumn("수 량", min_value=0, step=1),
            "단가(부가세불포)": st.column_config.NumberColumn("단 가(부가세불포)", min_value=0.0, step=100.0, format="%.2f"),
            "비고": st.column_config.TextColumn("비 고")
        },
        width="stretch",
        num_rows="dynamic",
        key="po_editor"
    )
    
    selected_items = edited_df[(edited_df["선택"] == True) | (edited_df["수량"] > 0)].copy()
    
    if selected_items.empty:
        st.warning("⚠️ 발주할 품목을 선택하거나 수량을 1 이상 입력해 주세요.")
        return

    selected_items["수량"] = pd.to_numeric(selected_items["수량"], errors="coerce").fillna(0)
    selected_items["단가(부가세불포)"] = pd.to_numeric(selected_items["단가(부가세불포)"], errors="coerce").fillna(0)
    selected_items["금액"] = selected_items["수량"] * selected_items["단가(부가세불포)"]
    
    total_qty = int(selected_items["수량"].sum())
    total_amount = selected_items["금액"].sum()
    
    if total_qty == 0:
        st.info("💡 위 표에서 발주할 품목의 **'수량'**과 **'단가'**를 입력하시면 아래 합계 금액과 인쇄 양식에 실시간으로 반영됩니다.")
    
    curr_symbol = "₩" if "KRW" in currency else "$"
    fmt = ",.0f" if "KRW" in currency else ",.2f"
    
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("총 발주 품목 수", f"{len(selected_items)} 개")
    m2.metric("총 발주 수량 합계", f"{total_qty:,} 개(Box)")
    m3.metric("합계 금액 (부가세불포)", f"{curr_symbol} {total_amount:{fmt}}")

    st.markdown("### 📄 발주서 미리보기 및 내보내기")
    
    # 엑셀 다운로드 (실제 양식 컬럼 매칭)
    export_df = selected_items[["상품명", "단가(부가세불포)", "수량", "금액", "비고"]].copy()
    export_df.insert(0, "NO", range(1, len(export_df) + 1))
    export_df.rename(columns={"상품명": "제 품 명", "단가(부가세불포)": "단 가(부가세불포)", "수량": "수 량", "금액": "금 액", "비고": "비 고"}, inplace=True)
    
    excel_data = to_excel(export_df, sheet_name="발주서")
    
    dl_col1, dl_col2 = st.columns([1, 4])
    with dl_col1:
        st.download_button(
            label="📥 발주서 엑셀(.xlsx) 다운로드",
            data=excel_data,
            file_name=f"발주서_{supplier}_{order_date.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
    with dl_col2:
        st.caption("💡 **인쇄 팁:** 브라우저 인쇄(`Ctrl + P`) 시 A4 가로/세로 용지에 꼭 맞게 실제 서흥 발주서 양식 스타일로 출력됩니다.")
        
    # HTML 인쇄 템플릿 (실제 PDF 양식 100% 이식)
    rows_html = ""
    for idx, (_, row) in enumerate(selected_items.iterrows(), 1):
        amt_str = f"{row['금액']:,.2f}" if "USD" in currency else f"{row['금액']:,.0f}"
        price_str = f"{row['단가(부가세불포)']:,.2f}" if "USD" in currency else f"{row['단가(부가세불포)']:,.0f}"
        rows_html += f"""
        <tr>
            <td style="text-align:center; padding:12px 8px; border:1px solid #475569;">{idx}</td>
            <td style="padding:12px 8px; border:1px solid #475569; font-weight:600; color:#0f172a;">{row['상품명']}</td>
            <td style="text-align:right; padding:12px 8px; border:1px solid #475569;">{curr_symbol} {price_str}</td>
            <td style="text-align:right; padding:12px 8px; border:1px solid #475569; font-weight:700;">{int(row['수량']):,}</td>
            <td style="text-align:right; padding:12px 8px; border:1px solid #475569; font-weight:700; color:#1e3a8a;">{curr_symbol} {amt_str}</td>
            <td style="padding:12px 8px; border:1px solid #475569; color:#475569; font-size:13px;">{row['비고']}</td>
        </tr>
        """
        
    html_po = f"""
    <div style="background:#ffffff; padding:45px; border:2px solid #334155; border-radius:8px; color:#1e293b; font-family:'Pretendard', sans-serif; max-width:900px; margin:0 auto; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
        <div style="text-align:center; margin-bottom:30px;">
            <h1 style="font-size:32px; font-weight:900; margin:0; color:#0f172a; letter-spacing:4px; border-bottom:3px double #0f172a; display:inline-block; padding-bottom:5px;">발 주 서</h1>
        </div>
        
        <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:20px; font-size:15px;">
            <div>
                <h2 style="margin:0; font-size:22px; font-weight:800; color:#0f172a;">{supplier} &nbsp;귀하</h2>
            </div>
            <div style="text-align:right; color:#334155;">
                <p style="margin:0 0 5px 0;"><strong>발주일 :</strong> {order_date.strftime('%Y. %m. %d')}</p>
                <p style="margin:0; color:#dc2626;"><strong>납품요청일 :</strong> {delivery_date.strftime('%Y. %m. %d')}</p>
            </div>
        </div>
        
        <div style="background:#f8fafc; border:1px solid #cbd5e1; padding:12px 18px; border-radius:6px; margin-bottom:25px; display:flex; justify-content:space-between; align-items:center; font-size:14px; color:#1e293b;">
            <span>* 상기와 같이 제품을 발주합니다.</span>
            <div>
                <span style="margin-right:20px;"><strong>업체명 :</strong> 주식회사 오니스트</span>
                <span><strong>담당자 :</strong> {mgr_name}</span>
            </div>
        </div>
        
        <table style="width:100%; border-collapse:collapse; margin-bottom:25px; font-size:14px;">
            <thead>
                <tr style="background:#1e293b; color:#ffffff; text-align:center;">
                    <th style="padding:12px 8px; border:1px solid #1e293b; width:50px;">NO</th>
                    <th style="padding:12px 8px; border:1px solid #1e293b;">제 품 명</th>
                    <th style="padding:12px 8px; border:1px solid #1e293b; width:130px;">단 가(부가세불포)</th>
                    <th style="padding:12px 8px; border:1px solid #1e293b; width:90px;">수 량</th>
                    <th style="padding:12px 8px; border:1px solid #1e293b; width:140px;">금 액</th>
                    <th style="padding:12px 8px; border:1px solid #1e293b;">비 고</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
            <tfoot>
                <tr style="background:#f1f5f9; font-weight:800; text-align:right; font-size:16px;">
                    <td colspan="3" style="text-align:center; padding:12px 8px; border:1px solid #475569; color:#0f172a;">합 &nbsp; &nbsp; 계</td>
                    <td style="padding:12px 8px; border:1px solid #475569; color:#0f172a;">{total_qty:,}</td>
                    <td style="padding:12px 8px; border:1px solid #475569; color:#2563eb;">{curr_symbol} {total_amount:{fmt}}</td>
                    <td style="border:1px solid #475569;"></td>
                </tr>
            </tfoot>
        </table>
        
        <div style="text-align:right; font-size:14px; color:#64748b; margin-top:40px; border-top:1px dashed #cbd5e1; padding-top:20px;">
            <p style="margin:0;">주식회사 오니스트 (Ownist Co., Ltd.)</p>
        </div>
    </div>
    """
    
    html_po = "\n".join([line.strip() for line in html_po.split("\n")])
    st.markdown(html_po, unsafe_allow_html=True)


# ────────────────────────────────────────────────
# 3. 박스별 입고라벨지 작성 (Formtec Box Label Generator)
# ────────────────────────────────────────────────
def render_label_generator(master_df: pd.DataFrame):
    st.markdown('<div class="sec-title">🏷️ 박스 입고라벨지(폼텍 양식) 작성</div>', unsafe_allow_html=True)
    st.info("💡 공장 입고 또는 물류센터 적치 시 박스 외부에 부착하는 A4 규격 입고 라벨지(폼텍 표준 양식)를 즉시 생성하고 인쇄할 수 있습니다.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        formtec_type = st.selectbox("라벨지 규격 (폼텍 표준 양식)", [
            "폼텍 3104 / 3604 (A4 4칸 - 105 x 148 mm, 박스 입고용 표준)",
            "폼텍 3108 (A4 8칸 - 99 x 68 mm)",
            "폼텍 3110 (A4 10칸 - 99 x 57 mm)",
            "폼텍 3114 (A4 14칸 - 99 x 38 mm)"
        ])
    with col2:
        prod_names = sorted(master_df["상품명"].dropna().unique().tolist())
        selected_prod = st.selectbox("인쇄할 상품 선택", prod_names)
        match_row = master_df[master_df["상품명"] == selected_prod].iloc[0] if not master_df[master_df["상품명"] == selected_prod].empty else None
        prod_code = match_row["상품코드"] if match_row is not None else "CODE-000"
        prod_sticks = match_row["내포입"] if match_row is not None else 1
    with col3:
        box_qty = st.number_input("인쇄할 박스 수량 (라벨 장수)", min_value=1, max_value=500, value=10, step=1)
        
    col_lot, col_exp, col_start, col_opt = st.columns([1, 1, 1, 1.5])
    with col_lot:
        lot_no = st.text_input("제조번호 (Lot No.)", value=f"L{date.today().strftime('%Y%m')}-01")
    with col_exp:
        exp_date = st.date_input("유통기한 (EXP)", value=date.today() + timedelta(days=730))
    with col_start:
        cells_per_page = 4 if "4칸" in formtec_type else (8 if "8칸" in formtec_type else (10 if "10칸" in formtec_type else 14))
        start_idx = st.number_input("시작 칸 위치 (빈 칸 수)", min_value=0, max_value=cells_per_page-1, value=0, help="이미 사용한 라벨 시트일 경우, 쓴 칸 수만큼 건너뛰고 인쇄합니다.")
    with col_opt:
        show_box_num = st.checkbox("박스 일련번호 (Box 1/N) 표시", value=True)
        show_barcode_box = st.checkbox("바코드 / 검수 확인란 표시", value=True)

    st.divider()
    
    label_list = []
    for i in range(1, box_qty + 1):
        label_list.append({
            "박스번호": f"BOX {i} / {box_qty}",
            "상품코드": prod_code,
            "상품명": selected_prod,
            "제조번호(Lot)": lot_no,
            "유통기한(EXP)": exp_date.strftime("%Y-%m-%d"),
            "내포입(포)": f"{int(prod_sticks):,} 포"
        })
    df_labels = pd.DataFrame(label_list)
    excel_data = to_excel(df_labels, sheet_name="박스라벨내역")
    
    dl_col1, dl_col2 = st.columns([1, 4])
    with dl_col1:
        st.download_button(
            label="📥 라벨 내역 엑셀 다운로드",
            data=excel_data,
            file_name=f"박스라벨_{prod_code}_{lot_no}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
    with dl_col2:
        st.caption(f"💡 **인쇄 팁:** 브라우저 인쇄(`Ctrl + P`) 시 여백을 **'없음' 또는 '최소'**로 설정하시고 **'배경 그래픽 인쇄'**를 켜시면 {formtec_type.split(' ')[0]} 라벨지 칸에 정확히 맞춰 인쇄됩니다.")

    grid_cols = 2
    if cells_per_page == 4:
        grid_rows = 2
        min_height = "440px"
        font_size_title = "20px"
        font_size_body = "15px"
    elif cells_per_page == 8:
        grid_rows = 4
        min_height = "220px"
        font_size_title = "16px"
        font_size_body = "13px"
    elif cells_per_page == 10:
        grid_rows = 5
        min_height = "175px"
        font_size_title = "15px"
        font_size_body = "12px"
    else:
        grid_rows = 7
        min_height = "125px"
        font_size_title = "13px"
        font_size_body = "11px"

    labels_html = ""
    total_slots = start_idx + box_qty
    
    for slot in range(total_slots):
        if slot < start_idx:
            labels_html += f'<div style="min-height:{min_height}; border:1px dashed #e2e8f0; border-radius:6px; opacity:0.3; display:flex; align-items:center; justify-content:center; color:#94a3b8;">(빈 칸)</div>'
        else:
            box_idx = slot - start_idx + 1
            box_num_str = f"BOX {box_idx} / {box_qty}" if show_box_num else "INVENTORY LABEL"
            
            barcode_html = ""
            if show_barcode_box:
                barcode_html = f"""
                <div style="margin-top:10px; border-top:1px dashed #cbd5e1; padding-top:6px; display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-family:monospace; font-size:11px; color:#64748b; letter-spacing:2px;">||| | |||| || | |||| ||</div>
                    <div style="font-size:11px; color:#475569; border:1px solid #cbd5e1; padding:2px 6px; border-radius:3px;">검수확인 [ &nbsp; &nbsp; ]</div>
                </div>
                """
                
            labels_html += f"""
            <div style="min-height:{min_height}; background:#ffffff; border:2px solid #334155; border-radius:8px; padding:16px; display:flex; flex-direction:column; justify-content:space-between; box-sizing:border-box; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #0f172a; padding-bottom:6px; margin-bottom:8px;">
                        <span style="font-size:12px; font-weight:700; color:#2563eb; background:#eff6ff; padding:2px 6px; border-radius:4px;">{prod_code}</span>
                        <strong style="font-size:13px; color:#0f172a; background:#f1f5f9; padding:2px 8px; border-radius:4px;">{box_num_str}</strong>
                    </div>
                    <h3 style="margin:0 0 10px 0; font-size:{font_size_title}; font-weight:800; color:#0f172a; line-height:1.3; word-break:keep-all;">{selected_prod}</h3>
                    <div style="font-size:{font_size_body}; color:#334155; line-height:1.6;">
                        <div>• <strong>제조번호(Lot):</strong> <span style="font-family:monospace; font-weight:700; color:#0f172a;">{lot_no}</span></div>
                        <div>• <strong>유통기한(EXP):</strong> <span style="font-weight:700; color:#dc2626;">{exp_date.strftime('%Y. %m. %d')}</span></div>
                        <div>• <strong>박스 입수량:</strong> <span style="font-weight:700; color:#0f172a;">{int(prod_sticks):,} 포 (EA)</span></div>
                    </div>
                </div>
                {barcode_html}
            </div>
            """

    page_html = f"""
    <div style="max-width:900px; margin:0 auto; background:#f8fafc; padding:20px; border-radius:8px; border:1px solid #cbd5e1;">
        <div style="display:grid; grid-template-columns:repeat({grid_cols}, 1fr); gap:15px;">
            {labels_html}
        </div>
    </div>
    """
    
    page_html = "\n".join([line.strip() for line in page_html.split("\n")])
    st.markdown("### 📄 라벨 인쇄 미리보기")
    st.markdown(page_html, unsafe_allow_html=True)


# ────────────────────────────────────────────────
# 4. 패킹리스트 / 거래명세서 작성 - 실제 양식 100% 반영
# ────────────────────────────────────────────────
def render_packing_list_generator(master_df: pd.DataFrame):
    st.markdown('<div class="sec-title">📄 패킹리스트 / 거래명세서 작성</div>', unsafe_allow_html=True)
    st.info("💡 **실무 양식 반영 완료:** 국내 거래명세서(표준 양식)와 네이버 도착보장 물류 입고용 **[PLT별 부착 패킹리스트]**, 영문 수출 상업송장을 모드별로 선택해 출력할 수 있습니다.")
    
    doc_mode = st.radio("문서 양식 선택", [
        "🇰🇷 거래명세서 (표준 양식)",
        "📦 PLT별 부착 패킹리스트 (네이버 도착보장 등 물류센터 입고용)",
        "🇺🇸 영문 수출용 Commercial Invoice & Packing List"
    ], horizontal=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if "PLT별" in doc_mode:
            plt_num = st.selectbox("파렛트 번호 선택", [f"PLT {i}" for i in range(1, 11)], index=0)
            doc_title_str = f"■ 거래명세서 ({plt_num})"
        elif "영문" in doc_mode:
            doc_title_str = "COMMERCIAL INVOICE & PACKING LIST"
            inv_no = st.text_input("Invoice No.", value=f"INV-{date.today().strftime('%Y%m%d')}-01")
        else:
            doc_title_str = "■ 거래명세서"
    with col2:
        ship_date = st.date_input("출고 / 일자", value=date.today())
    with col3:
        if "영문" in doc_mode:
            vessel_info = st.text_input("Vessel / Port", value="Busan ➔ Los Angeles, CA")
        else:
            note_info = st.text_input("비고 / 물류 전달사항", value="네이버 도착보장 물류센터 입고" if "PLT별" in doc_mode else "CK로지스 창고 이동")

    st.markdown("##### 📌 출고 / 선적 품목 명세")
    st.caption("해당 문서(또는 파렛트)에 포함될 품목의 **'선택'**을 켜고 **'수량'**(포/개수) 또는 **'BOX'**를 입력하세요.")
    
    df_init = master_df[["상품코드", "상품명", "내포입"]].drop_duplicates(subset=["상품코드"]).copy()
    df_init["선택"] = False
    df_init["수량(EA)"] = 0
    df_init["BOX"] = 0
    if "영문" in doc_mode:
        df_init["단가(USD)"] = 15.00
        df_init["중량(kg)"] = 5.5
        df_init["CBM"] = 0.025
        df_init = df_init[["선택", "상품코드", "상품명", "내포입", "BOX", "수량(EA)", "단가(USD)", "중량(kg)", "CBM"]]
    else:
        df_init = df_init[["선택", "상품코드", "상품명", "내포입", "수량(EA)", "BOX"]]
        
    edited_df = st.data_editor(
        df_init,
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", default=False),
            "상품코드": st.column_config.TextColumn("상품코드", disabled=True),
            "상품명": st.column_config.TextColumn("상품명", disabled=True),
            "내포입": st.column_config.NumberColumn("박스입수", disabled=True),
            "수량(EA)": st.column_config.NumberColumn("수량", min_value=0, step=1),
            "BOX": st.column_config.NumberColumn("BOX", min_value=0, step=1)
        },
        width="stretch",
        num_rows="dynamic",
        key="pl_editor"
    )
    
    selected_items = edited_df[(edited_df["선택"] == True) | (edited_df["수량(EA)"] > 0) | (edited_df["BOX"] > 0)].copy()
    
    if selected_items.empty:
        st.warning("⚠️ 품목을 선택하거나 수량/BOX를 1 이상 입력해 주세요.")
        return

    selected_items["내포입"] = pd.to_numeric(selected_items["내포입"], errors="coerce").fillna(1)
    selected_items["수량(EA)"] = pd.to_numeric(selected_items["수량(EA)"], errors="coerce").fillna(0)
    selected_items["BOX"] = pd.to_numeric(selected_items["BOX"], errors="coerce").fillna(0)
    
    # 수량이나 BOX 중 하나만 입력된 경우 자동 동기화 계산
    for idx in selected_items.index:
        q = selected_items.loc[idx, "수량(EA)"]
        b = selected_items.loc[idx, "BOX"]
        pack = selected_items.loc[idx, "내포입"]
        if q > 0 and b == 0:
            selected_items.loc[idx, "BOX"] = int(math.ceil(q / pack)) if pack > 0 else 0
        elif b > 0 and q == 0:
            selected_items.loc[idx, "수량(EA)"] = int(b * pack)

    tot_qty = int(selected_items["수량(EA)"].sum())
    tot_box = int(selected_items["BOX"].sum())

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("총 품목 수", f"{len(selected_items)} 품목")
    m2.metric("수량 합계 (EA)", f"{tot_qty:,} 개")
    m3.metric("BOX 합계", f"{tot_box:,} 박스")

    st.markdown("### 📄 문서 미리보기 및 내보내기")
    
    # ── [모드 1 & 2: 국내 거래명세서 및 PLT별 패킹리스트] ──
    if "영문" not in doc_mode:
        if "PLT별" in doc_mode:
            export_df = selected_items[["상품코드", "상품명", "내포입", "수량(EA)", "BOX"]].copy()
            export_df.insert(0, "No", range(1, len(export_df) + 1))
            export_df.rename(columns={"내포입": "박스입수", "수량(EA)": "수량"}, inplace=True)
            sheet_nm = plt_num.replace(" ", "")
        else:
            export_df = selected_items[["상품명", "내포입", "수량(EA)", "BOX"]].copy()
            export_df.insert(0, "No", range(1, len(export_df) + 1))
            export_df.rename(columns={"내포입": "박스입수", "수량(EA)": "수량"}, inplace=True)
            sheet_nm = "거래명세서"
            
        excel_data = to_excel(export_df, sheet_name=sheet_nm)
        
        dl_col1, dl_col2 = st.columns([1, 4])
        with dl_col1:
            st.download_button(
                label=f"📥 {sheet_nm} 엑셀(.xlsx) 다운로드",
                data=excel_data,
                file_name=f"{sheet_nm}_{ship_date.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch"
            )
        with dl_col2:
            st.caption("💡 **인쇄 팁:** 브라우저 인쇄(`Ctrl + P`) 시 아래 미리보기 양식이 실제 오니스트 거래명세서 엑셀 템플릿과 동일한 비율로 출력됩니다.")
            
        rows_html = ""
        for idx, (_, row) in enumerate(selected_items.iterrows(), 1):
            code_td = f'<td style="text-align:center; padding:10px; border:1px solid #475569;">{row["상품코드"]}</td>' if "PLT별" in doc_mode else ""
            rows_html += f"""
            <tr>
                <td style="text-align:center; padding:10px; border:1px solid #475569;">{idx}</td>
                {code_td}
                <td style="padding:10px; border:1px solid #475569; font-weight:600; color:#0f172a;">{row['상품명']}</td>
                <td style="text-align:right; padding:10px; border:1px solid #475569;">{int(row['내포입']):,}</td>
                <td style="text-align:right; padding:10px; border:1px solid #475569; font-weight:700; color:#1e3a8a;">{int(row['수량(EA)']):,}</td>
                <td style="text-align:right; padding:10px; border:1px solid #475569; font-weight:700; color:#0f172a;">{int(row['BOX']):,}</td>
            </tr>
            """
            
        code_th = '<th style="padding:10px; border:1px solid #1e293b; width:140px;">상품코드</th>' if "PLT별" in doc_mode else ""
        colspan_foot = 3 if "PLT별" in doc_mode else 2
        
        html_doc = f"""
        <div style="background:#ffffff; padding:45px; border:2px solid #334155; border-radius:8px; color:#1e293b; font-family:'Pretendard', sans-serif; max-width:900px; margin:0 auto; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
            <div style="margin-bottom:25px;">
                <h1 style="font-size:26px; font-weight:900; margin:0 0 15px 0; color:#0f172a;">{doc_title_str}</h1>
                <div style="border:2px solid #0f172a; display:flex; font-size:13px;">
                    <div style="background:#f1f5f9; padding:15px 20px; font-weight:800; display:flex; align-items:center; border-right:2px solid #0f172a; color:#0f172a; width:70px; justify-content:center;">
                        공급자
                    </div>
                    <div style="padding:15px 20px; flex-grow:1; line-height:1.8;">
                        <div style="display:flex; justify-content:space-between; border-bottom:1px dashed #cbd5e1; padding-bottom:6px; margin-bottom:6px;">
                            <span><strong>사업자등록번호 :</strong> 418-87-02030</span>
                            <span><strong>대표자 :</strong> 김재현</span>
                        </div>
                        <div style="border-bottom:1px dashed #cbd5e1; padding-bottom:6px; margin-bottom:6px;">
                            <strong>상호명 :</strong> 주식회사 오니스트 (셀러코드 : 90015601)
                        </div>
                        <div>
                            <strong>주소 :</strong> 서울특별시 영등포구 여의대로 108 파크원타워1 517호
                        </div>
                    </div>
                </div>
            </div>
            
            <div style="text-align:right; font-size:13px; color:#475569; margin-bottom:10px;">
                <strong>일자 :</strong> {ship_date.strftime('%Y년 %m월 %d일')}
            </div>
            
            <table style="width:100%; border-collapse:collapse; margin-bottom:25px; font-size:14px;">
                <thead>
                    <tr style="background:#1e293b; color:#ffffff; text-align:center;">
                        <th style="padding:10px; border:1px solid #1e293b; width:50px;">No</th>
                        {code_th}
                        <th style="padding:10px; border:1px solid #1e293b;">상 품 명</th>
                        <th style="padding:10px; border:1px solid #1e293b; width:100px;">박스입수</th>
                        <th style="padding:10px; border:1px solid #1e293b; width:100px;">수 량</th>
                        <th style="padding:10px; border:1px solid #1e293b; width:90px;">BOX</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
                <tfoot>
                    <tr style="background:#f8fafc; font-weight:800; text-align:center; font-size:15px; color:#0f172a;">
                        <td colspan="{colspan_foot}" style="padding:12px 10px; border:1px solid #475569; text-align:left;">
                            <span style="color:#64748b; font-weight:600; margin-right:15px;">납품브랜드 :</span>주식회사 오니스트
                        </td>
                        <td style="padding:12px 10px; border:1px solid #475569; text-align:center; background:#f1f5f9;">합 계</td>
                        <td style="padding:12px 10px; border:1px solid #475569; text-align:right; color:#1e3a8a;">{tot_qty:,}</td>
                        <td style="padding:12px 10px; border:1px solid #475569; text-align:right; color:#0f172a;">{tot_box:,}</td>
                    </tr>
                </tfoot>
            </table>
        </div>
        """
        html_doc = "\n".join([line.strip() for line in html_doc.split("\n")])
        st.markdown(html_doc, unsafe_allow_html=True)
        
    # ── [모드 3: 영문 수출용 Commercial Invoice & Packing List] ──
    else:
        selected_items["단가(USD)"] = pd.to_numeric(selected_items["단가(USD)"], errors="coerce").fillna(0.0)
        selected_items["중량(kg)"] = pd.to_numeric(selected_items["중량(kg)"], errors="coerce").fillna(0.0)
        selected_items["CBM"] = pd.to_numeric(selected_items["CBM"], errors="coerce").fillna(0.0)
        selected_items["금액(USD)"] = selected_items["BOX"] * selected_items["단가(USD)"]
        selected_items["총중량(kg)"] = selected_items["BOX"] * selected_items["중량(kg)"]
        selected_items["총CBM"] = selected_items["BOX"] * selected_items["CBM"]
        
        tot_amt = selected_items["금액(USD)"].sum()
        tot_gw = selected_items["총중량(kg)"].sum()
        tot_cbm = selected_items["총CBM"].sum()
        
        export_df = selected_items[["상품코드", "상품명", "내포입", "BOX", "수량(EA)", "단가(USD)", "금액(USD)", "총중량(kg)", "총CBM"]].copy()
        excel_data = to_excel(export_df, sheet_name="Invoice_PackingList")
        
        dl_col1, dl_col2 = st.columns([1, 4])
        with dl_col1:
            st.download_button(
                label="📥 영문 인보이스/패킹리스트 엑셀 다운로드",
                data=excel_data,
                file_name=f"CI_PL_{inv_no}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch"
            )
        with dl_col2:
            st.caption("💡 **인쇄 팁:** 수출 신고 및 미국 세관 제출용 영문 상업송장/패킹리스트 양식입니다.")
            
        rows_html = ""
        for idx, (_, row) in enumerate(selected_items.iterrows(), 1):
            rows_html += f"""
            <tr>
                <td style="text-align:center; padding:8px; border:1px solid #cbd5e1;">{row['상품코드']}</td>
                <td style="padding:8px; border:1px solid #cbd5e1; font-weight:600;">{row['상품명']}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1;">{int(row['BOX']):,}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1;">{int(row['수량(EA)']):,}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1;">{row['총중량(kg)']:,.1f}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1;">{row['총CBM']:,.3f}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1;">$ {row['단가(USD)']:,.2f}</td>
                <td style="text-align:right; padding:8px; border:1px solid #cbd5e1; font-weight:700; color:#2563eb;">$ {row['금액(USD)']:,.2f}</td>
            </tr>
            """

        html_doc = f"""
        <div style="background:#ffffff; padding:45px; border:1px solid #cbd5e1; border-radius:8px; color:#1e293b; font-family:'Pretendard', sans-serif; max-width:900px; margin:0 auto; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
            <div style="text-align:center; border-bottom:3px solid #0f172a; padding-bottom:15px; margin-bottom:25px;">
                <h1 style="font-size:26px; font-weight:800; margin:0; color:#0f172a; letter-spacing:1px;">COMMERCIAL INVOICE & PACKING LIST</h1>
                <p style="margin:6px 0 0 0; color:#64748b; font-size:14px;">No: <strong style="color:#0f172a;">{inv_no}</strong> &nbsp; | &nbsp; Date: <strong style="color:#0f172a;">{ship_date.strftime('%Y-%m-%d')}</strong></p>
            </div>
            
            <div style="display:flex; justify-content:space-between; margin-bottom:25px; font-size:13px; line-height:1.6;">
                <div style="width:48%; background:#f8fafc; padding:15px; border-radius:6px; border:1px solid #e2e8f0;">
                    <strong style="color:#0f172a; font-size:14px; display:block; border-bottom:1px solid #cbd5e1; padding-bottom:4px; margin-bottom:6px;">SHIPPER / EXPORTER</strong>
                    <pre style="margin:0; font-family:inherit; white-space:pre-wrap; color:#334155;">Ownist Co., Ltd.\nRoom 517, Tower 1, Parc.1, 108 Yeoui-daero, Yeongdeungpo-gu, Seoul, Korea\nTel: +82-2-1234-5678 / Biz Reg: 418-87-02030</pre>
                </div>
                <div style="width:48%; background:#f8fafc; padding:15px; border-radius:6px; border:1px solid #e2e8f0;">
                    <strong style="color:#0f172a; font-size:14px; display:block; border-bottom:1px solid #cbd5e1; padding-bottom:4px; margin-bottom:6px;">CONSIGNEE / IMPORTER</strong>
                    <pre style="margin:0; font-family:inherit; white-space:pre-wrap; color:#334155;">[CGETC] Los Angeles Fulfillment Center, CA, USA\nAttn: Logistics & Fulfillment Team\nRoute: {vessel_info}</pre>
                </div>
            </div>
            
            <table style="width:100%; border-collapse:collapse; margin-bottom:25px; font-size:13px;">
                <thead>
                    <tr style="background:#0f172a; color:#ffffff; text-align:center;">
                        <th style="padding:10px; border:1px solid #0f172a;">Code</th>
                        <th style="padding:10px; border:1px solid #0f172a;">Description</th>
                        <th style="padding:10px; border:1px solid #0f172a;">Box</th>
                        <th style="padding:10px; border:1px solid #0f172a;">Total Qty</th>
                        <th style="padding:10px; border:1px solid #0f172a;">G.W(kg)</th>
                        <th style="padding:10px; border:1px solid #0f172a;">CBM</th>
                        <th style="padding:10px; border:1px solid #0f172a;">Unit Price</th>
                        <th style="padding:10px; border:1px solid #0f172a;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
                <tfoot>
                    <tr style="background:#f1f5f9; font-weight:700; text-align:right;">
                        <td colspan="2" style="text-align:center; padding:10px; border:1px solid #cbd5e1;">TOTAL</td>
                        <td style="padding:10px; border:1px solid #cbd5e1;">{tot_box:,}</td>
                        <td style="padding:10px; border:1px solid #cbd5e1;">{tot_qty:,}</td>
                        <td style="padding:10px; border:1px solid #cbd5e1;">{tot_gw:,.1f}</td>
                        <td style="padding:10px; border:1px solid #cbd5e1;">{tot_cbm:,.3f}</td>
                        <td style="padding:10px; border:1px solid #cbd5e1;"></td>
                        <td style="padding:10px; border:1px solid #cbd5e1; color:#2563eb;">$ {tot_amt:,.2f}</td>
                    </tr>
                </tfoot>
            </table>
            
            <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid #cbd5e1; padding-top:20px; font-size:13px; color:#475569;">
                <div>
                    <p style="margin:0;">* We certify that this invoice and packing list is true and correct in all respects.</p>
                    <p style="margin:4px 0 0 0; font-weight:600; color:#0f172a;">OWNIST LOGISTICS & SCM TEAM</p>
                </div>
                <div style="text-align:center; width:220px;">
                    <p style="margin:0 0 35px 0; font-weight:600;">Authorized Signature</p>
                    <div style="border-bottom:1px solid #64748b; padding-bottom:5px;">
                        <strong style="font-size:15px; color:#0f172a;">Ownist Co., Ltd.</strong>
                    </div>
                </div>
            </div>
        </div>
        """
        st.markdown(html_doc, unsafe_allow_html=True)
