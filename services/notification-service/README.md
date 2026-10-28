# Notification Service

Owner: Krishna Sagar    Review partner: Aishwarya

## Run (from this folder)
```
python -m venv .venv
.venv\Scripts\activate          (Windows)   |   source .venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env           (Windows)   |   cp .env.example .env
uvicorn app.main:app --port 8004 --reload
```
Check: http://localhost:8004/health  and  http://localhost:8004/docs

## Test
```
pytest
```

## Where things go
- `app/main.py`  - app setup (already done, do not change the error format)
- `app/api/`     - your routes under `/api/v1/...`
- `app/rules.py` - business rules (tag with BR ids)
- `app/db.py`    - your database code (own DB only: `notification_db`)
- `tests/`       - tests (name rule tests `test_BR<n>_...`)
