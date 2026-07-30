import asyncio
from playwright.async_api import async_playwright
import re
from datetime import datetime

async def scrape_tradlinx(target_carrier=None, origin="KRPUS", dest="USLAX"):
    """
    트레드링스(Tradlinx) 사이트를 스크래핑하여 실제 선박 스케줄을 가져옵니다.
    target_carrier가 주어지면 해당 선사의 데이터만 필터링합니다. (예: "HMM", "SM Line")
    """
    schedules = []
    
    # 임시 URL (KRPUS 105169 -> USLAX 105373) - 오늘 날짜 기준
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.tradlinx.com/ko/ocean-schedule-fcl?org=105169&des=105373&day={today_str}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            print(f"[Tradlinx Scraper] 접속 중... {url}")
            await page.goto(url, timeout=45000)
            
            # vessel-name-fcl 요소가 뜰 때까지 대기
            await page.wait_for_selector('a.vessel-name-fcl', timeout=20000)
            vessel_els = await page.query_selector_all('a.vessel-name-fcl')
            print(f"[Tradlinx Scraper] 총 {len(vessel_els)}개의 스케줄 요소 발견")
            
            for v in vessel_els:
                row = await page.evaluate_handle('el => el.closest(".row") || el.closest("div[style*=\\"border-bottom\\"]") || el.parentElement.parentElement.parentElement', v)
                if not row:
                    continue
                
                text = await row.inner_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                
                if len(lines) >= 6:
                    carrier = lines[0]
                    vessel_name = lines[1]
                    # Origin은 lines[2]
                    etd_raw = lines[3] # e.g. "2026.07.30 (Thu)"
                    # Dest는 lines[4]
                    eta_raw = lines[5] # e.g. "2026.08.25 (Tue)"
                    
                    etd = etd_raw.split(" ")[0].replace(".", "-")
                    eta = eta_raw.split(" ")[0].replace(".", "-")
                    
                    # carrier 필터링
                    if target_carrier and target_carrier.lower() not in carrier.lower():
                        continue
                        
                    # voyage 추출 시도 (보통 vessel_name의 마지막 단어가 voyage)
                    parts = vessel_name.split(" ")
                    voyage = parts[-1] if len(parts) > 1 else ""
                    v_name = " ".join(parts[:-1]) if len(parts) > 1 else vessel_name
                    
                    schedules.append({
                        "carrier": carrier,
                        "vessel_name": v_name,
                        "voyage_no": voyage,
                        "origin_port": origin,
                        "dest_port": dest,
                        "etd": etd,
                        "eta": eta
                    })
                    
        except Exception as e:
            print(f"[Tradlinx Scraper] 오류 발생: {e}")
        finally:
            await browser.close()
            
    return schedules
