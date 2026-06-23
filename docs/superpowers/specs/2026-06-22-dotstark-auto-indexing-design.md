# Design: DotStark Auto-Indexing

## Summary
Remove the "Index a Website" feature and auto-scrape dotstark.com on server startup.

## Changes

### 1. Backend - Auto-ingest on startup
- Add `@app.on_event("startup")` in `main.py`
- Hardcode `https://dotstark.com` as target URL
- Call `pipeline.ingest()` on startup

### 2. Config
- Add `TARGET_URL: str = "https://dotstark.com"` to `config.py`
- Add `AUTO_INGEST: bool = True` toggle

### 3. Frontend
- Remove "Index a Website" tab from `ChatWidget.jsx`
- Keep only Chat tab
- Update welcome message

### 4. Startup flow
```
Server starts → Load models → Crawl dotstark.com → Index chunks → Ready
```
