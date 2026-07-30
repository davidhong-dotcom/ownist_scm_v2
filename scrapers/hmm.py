import asyncio
from mof_api import fetch_mof_schedules

async def scrape_hmm_schedules(origin="KRPUS", dest="USLAX"):
    """
    해양수산부 API를 통해 HMM의 Port-to-Port 스케줄을 가져옵니다.
    """
    print(f"[HMM Scraper] 해양수산부 API 라이브 통신을 시작합니다...")
    schedules = await fetch_mof_schedules(target_carrier="HMM", origin=origin, dest=dest)
    
    # HMM 로직 (필요시 추가 가공)
    return schedules

if __name__ == "__main__":
    res = asyncio.run(scrape_hmm_schedules())
    print(f"HMM 스케줄: {len(res)}건 수집 완료")
    for r in res[:3]:
        print(r)
