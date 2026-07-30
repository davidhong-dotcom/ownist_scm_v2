import asyncio
from mof_api import fetch_mof_schedules

async def scrape_sm_line_schedules(origin="KRPUS", dest="USLAX"):
    """
    해양수산부 API를 통해 SM Line의 Port-to-Port 스케줄을 가져옵니다.
    """
    print(f"[SM Line Scraper] 해양수산부 API 라이브 통신을 시작합니다...")
    schedules = await fetch_mof_schedules(target_carrier="SML", origin=origin, dest=dest)
    
    # SM Line 로직 (필요시 추가 가공)
    return schedules

if __name__ == "__main__":
    res = asyncio.run(scrape_sm_line_schedules())
    print(f"SM Line 스케줄: {len(res)}건 수집 완료")
    for r in res[:3]:
        print(r)
