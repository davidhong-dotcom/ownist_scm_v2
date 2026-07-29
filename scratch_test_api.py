import requests
import xml.etree.ElementTree as ET
from datetime import date, timedelta, datetime

api_key = "64b0c7cd9e531882a7ffe39c6b7772ee067d6d49ba934c9976c855e1ef54f2e2"
url = "http://apis.data.go.kr/1192000/VsslEtrynd5/Info5"
start_date = date.today()
sde_str = start_date.strftime("%Y%m%d")
ede_str = (start_date + timedelta(days=30)).strftime("%Y%m%d")

params = {
    "serviceKey": api_key,
    "prtAgCd": "020",
    "sde": sde_str,
    "ede": ede_str,
    "deGb": "O",
    "pageNo": "1",
    "numOfRows": "100"
}

try:
    response = requests.get(url, params=params, timeout=10)
    print("Status Code:", response.status_code)
    
    # Check if there is an Open API Error message (data.go.kr returns HTML on error sometimes)
    if response.status_code != 200 or "<OpenAPI_ServiceResponse>" in response.text:
        print("Error Response Text:")
        print(response.text[:1000])
    else:
        root = ET.fromstring(response.content)
        header = root.find(".//header")
        if header is not None:
            code = header.findtext("resultCode")
            msg = header.findtext("resultMsg")
            print(f"API Result: {code} - {msg}")
            
        body = root.find(".//body")
        if body is not None:
            total_count = body.findtext("totalCount")
            print(f"Total Count: {total_count}")
            
        destinations = []
        la_ships = 0
        total_fetched = 0
        
        for page in range(1, 11):
            params["pageNo"] = str(page)
            response = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(response.content)
            items = root.findall(".//item")
            if not items:
                break
            
            total_fetched += len(items)
            for item in items:
                dstnNatPrtCd = item.findtext("dstnNatPrtCd", "")
                dstnPrtNm = item.findtext("dstnPrtNm", "")
                destinations.append(f"{dstnNatPrtCd} ({dstnPrtNm})")
                
                if "USLAX" in dstnNatPrtCd or "USLGB" in dstnNatPrtCd or "LOS ANGELES" in dstnPrtNm.upper() or "LONG BEACH" in dstnPrtNm.upper():
                    la_ships += 1
                    
            if len(items) < 50:
                break
                
        print(f"Total items fetched across pages: {total_fetched}")
        print(f"Number of LA/LGB ships found: {la_ships}")
        
        print("Sample destinations (up to 10):")
        for d in set(destinations[:10]):
            print(" -", d)
            
except Exception as e:
    print("Exception:", e)
