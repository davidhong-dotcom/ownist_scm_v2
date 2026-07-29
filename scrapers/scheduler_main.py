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
    
    if not schedules:
        print(f"[{datetime.now()}] 저장할 데이터가 없습니다.")
        return
        
    try:
        import toml
        from supabase import create_client, Client
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        secrets_path = os.path.join(project_root, ".streamlit", "secrets.toml")
        
        secrets = toml.load(secrets_path)
        url = secrets["supabase"]["url"]
        key = secrets["supabase"]["key"]
        
        supabase: Client = create_client(url, key)
        
        # 기존 데이터 모두 삭제 (업데이트 방식)
        supabase.table("shipping_master_schedules").delete().neq("id", 0).execute()
        
        # 새 데이터 일괄 삽입
        # insert takes a list of dicts
        res = supabase.table("shipping_master_schedules").insert(schedules).execute()
        
        print(f"[{datetime.now()}] 스크래핑 완료. 총 {len(schedules)}건이 Supabase DB에 저장되었습니다.")
        
    except Exception as e:
        print(f"[{datetime.now()}] Supabase 저장 중 오류 발생: {e}")

if __name__ == "__main__":
    main()
