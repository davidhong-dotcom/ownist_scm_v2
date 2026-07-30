import asyncio
from tradlinx_api import scrape_tradlinx

async def scrape_sm_line_schedules(origin="KRPUS", dest="USLAX"):
    """
    트레드링스(Tradlinx) 사이트에서 SM Line의 Port-to-Port 스케줄을 스크래핑합니다.
    (기존 가상 데이터 생성 로직 폐기)
    """
    print(f"[SM Line Scraper] 트레드링스 라이브 스크래핑을 시작합니다...")
    schedules = await scrape_tradlinx(target_carrier="SM Line", origin=origin, dest=dest)
    return schedules

if __name__ == "__main__":
    # 단독 실행 테스트용
    res = asyncio.run(scrape_sm_line_schedules())
    print(f"SM Line 스케줄: {len(res)}건 수집 완료")
    for r in res[:3]:
        print(r)
