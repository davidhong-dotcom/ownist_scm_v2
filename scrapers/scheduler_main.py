import asyncio
import json
import os
from datetime import datetime

# Import scraper functions
from hmm import scrape_hmm_schedules
from sm_line import scrape_sm_line_schedules

async def get_combined_schedules():
    """
    모든 스크래퍼를 병렬로 실행하여 통합된 스케줄 리스트를 반환합니다.
    """
    print(f"[{datetime.now()}] 스크래핑 파이프라인 시작...")
    
    # Run scrapers concurrently
    results = await asyncio.gather(
        scrape_hmm_schedules(),
        scrape_sm_line_schedules(),
        return_exceptions=True # Prevent one failure from stopping the whole pipeline
    )
    
    combined = []
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            print(f"스크래퍼 {idx} 실패: {res}")
        elif isinstance(res, list):
            combined.extend(res)
            
    # Sort by ETD
    combined.sort(key=lambda x: x["etd"])
    return combined

def main():
    schedules = asyncio.run(get_combined_schedules())
    
    # Save to JSON file
    # We should save it to the data directory at the project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    data_dir = os.path.join(project_root, "data")
    
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        
    output_path = os.path.join(data_dir, "master_schedules.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schedules, f, ensure_ascii=False, indent=2)
        
    print(f"[{datetime.now()}] 스크래핑 완료. 총 {len(schedules)}건이 {output_path}에 저장되었습니다.")

if __name__ == "__main__":
    main()
