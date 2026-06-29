# 📦 재고·출고 대시보드

Streamlit 기반 재고 관리 대시보드.  
**Antigravity 이관**을 고려하여 데이터 로직과 UI 로직을 완전히 분리한 모듈 구조입니다.

---

## 📁 프로젝트 구조

```
inventory_dashboard/
│
├── app.py                  # 진입점: 데이터 모듈 + UI 모듈 조합만 담당
│
├── data/
│   └── processor.py        # ★ 순수 데이터 처리 로직 (Pandas / 비즈니스 규칙)
│                           #   - 마스터 DB 로드 (Google Sheets / 파일)
│                           #   - 현재고 파일 파싱
│                           #   - 출고현황 파싱 · 필터링 · 집계
│                           #   - 지표 산출 (월평균, 일평균, 안전재고, 예상소진일)
│
├── ui/
│   └── components.py       # ★ Streamlit UI 컴포넌트 (화면 렌더링만 담당)
│                           #   - 사이드바, KPI 카드, 테이블, 필터, 다운로드
│
├── requirements.txt
└── README.md
```

---

## 🚀 실행 방법

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 앱 실행
streamlit run app.py
```

---

## 📊 데이터 소스 준비

### 마스터 DB (Google Sheets)
공유 설정 → **링크 있는 모든 사용자 뷰어** 후 아래 URL 형식 사용:

```
https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}
```

| 컬럼 | 설명 |
|------|------|
| 구분 | 대분류 |
| 품목구분 | 중분류 |
| 상품코드 | 고유 식별자 (조인 키) |
| 상품명 | 상품 이름 |

### 현재고 파일 (`현재고_YYYYMMDD_HHMMSS.xls`)
| 컬럼 | 설명 |
|------|------|
| 상품코드 | 마스터 DB 조인 키 |
| 현재고 | 현재 재고 수량 (콤마 포함 가능) |

### 일자별 출고현황 파일 (`일자별 출고현황_YYYYMMDD_HHMMSS.xls`)
| 컬럼 | 설명 |
|------|------|
| 상품코드 | 마스터 DB 조인 키 |
| 출고일자 | 날짜 (YYYY-MM-DD 또는 Excel 날짜 형식) |
| 출고수량 | 출고 수량 (콤마 포함 가능) |

---

## 🧮 지표 계산식

| 지표 | 계산식 |
|------|--------|
| 3개월 월평균 출고량 | 최근 90일 총출고량 ÷ 3 |
| 3개월 일평균 출고량 | 최근 90일 총출고량 ÷ 90 |
| 사용 가능(월) | 현재고 ÷ 월평균 출고량 |
| 사용 가능(일) | 현재고 ÷ 일평균 출고량 |
| 안전재고 | 월평균 출고량 × 1.5 |
| 안전재고 미만 | 현재고 − 안전재고 |
| 예상소진일 | KST 오늘 + 사용가능(일) |

> 출고량이 0인 경우 나눗셈 항목은 **"출고없음"** 으로 표시됩니다.

---

## 🔄 Antigravity 이관 가이드

| 교체 대상 | 방법 |
|-----------|------|
| `ui/components.py` | Antigravity 컴포넌트 API로 함수 재구현 |
| `app.py` | render_* 호출을 Antigravity 라우터/뷰로 교체 |
| `data/processor.py` | **변경 불필요** — 순수 Python/Pandas 로직 그대로 재사용 |
