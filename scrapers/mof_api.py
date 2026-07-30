import httpx
import json
from datetime import datetime, timedelta

async def fetch_mof_schedules(target_carrier=None, origin="KRPUS", dest="USLAX"):
    """
    해양수산부 수출입 물류공공·민간 데이터 공유 플랫폼 내부 API 호출
    (Playwright 없이 순수 HTTP POST 요청을 사용하여 속도 및 안정성 극대화)
    """
    url = "https://ldsp.mof.go.kr/lto/cki/cki011/searchComVslSchList.do"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=\"UTF-8\"",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    today = datetime.now()
    start_dt = today.strftime("%Y%m%d")
    end_dt = (today + timedelta(days=45)).strftime("%Y%m%d")  # 45일치 조회
    
    payload = {
        "dma_search": {
            "ONS_ID": "",
            "POL_CD": origin,
            "POD_CD": dest,
            "POL_ETD_START_DT": start_dt,
            "POL_ETD_END_DT": end_dt,
            "POD_ETA_START_DT": start_dt,
            "POD_ETA_END_DT": (today + timedelta(days=90)).strftime("%Y%m%d"),
            "TRAN_DYS": "",
            "CRYR_CD": "",
            "page": 1,
            "rowCount": 200
        }
    }
    
    schedules = []
    
    try:
        print(f"[MOF Scraper] 해양수산부 API 요청 중... (Carrier: {target_carrier or 'ALL'})")
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=20.0)
            
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("dlt_list", [])
                print(f"[MOF Scraper] 응답 데이터 총 {len(items)}건 수신 완료")
                
                for item in items:
                    carrier = item.get("CRYR_CD", "")
                    
                    if target_carrier and target_carrier.lower() not in carrier.lower():
                        continue
                    
                    # 날짜 형식 변환: "2026-07-30(THU)" -> "2026-07-30"
                    etd_raw = item.get("POL_ETD_DT", "")
                    eta_raw = item.get("POD_ETA_DT", "")
                    cgo_raw = item.get("CGO_DL_DT", "")
                    etd = etd_raw.split("(")[0] if "(" in etd_raw else etd_raw
                    eta = eta_raw.split("(")[0] if "(" in eta_raw else eta_raw
                    cgo = cgo_raw.split("(")[0] if "(" in cgo_raw else cgo_raw
                    if not cgo:
                        cgo = etd # 반입 마감일이 없으면 출항일과 동일하게 처리
                    
                    schedules.append({
                        "carrier": carrier,
                        "vessel_name": item.get("VSL_NM", ""),
                        "voyage_no": item.get("VOY_NR_DIR_CD", ""),
                        "origin_port": item.get("POL_CD", origin),
                        "dest_port": item.get("POD_CD", dest),
                        "etd": etd,
                        "eta": eta,
                        "cargo_cutoff": cgo
                    })
            else:
                print(f"[MOF Scraper] HTTP 에러: {resp.status_code}")
                print(resp.text[:500])
                
    except Exception as e:
        print(f"[MOF Scraper] API 호출 중 오류 발생: {e}")
        
    return schedules
