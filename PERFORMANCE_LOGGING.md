# Get-Stakeholders Performance Logging Guide

## Performance Logs Added

The optimized `/get-stakeholders` endpoint now includes detailed RED performance logging to help diagnose bottlenecks.

## Log Output Examples

### First Call (No Cache)
```
#### Getting stakeholders for deal: Acme Corp Deal
[PERFORMANCE] MongoDB query took: 45.32 ms
Found 10 unique stakeholders for deal Acme Corp Deal
[PERFORMANCE] Stakeholder extraction took: 47.18 ms
[CACHE MISS] Analyzing title 'VP of Engineering' via LLM
[CACHE MISS] Analyzing title 'Software Engineer' via LLM
[CACHE MISS] Analyzing title 'Director of Product' via LLM
... (more LLM calls in parallel)
[PERFORMANCE] LLM analysis (parallel) took: 1843.21 ms
[PERFORMANCE] ========================================
[PERFORMANCE] TOTAL get-stakeholders took: 1935.67 ms (1.94 seconds)
[PERFORMANCE] Found 10 stakeholders for deal: Acme Corp Deal
[PERFORMANCE] ========================================
```

### Second Call (Endpoint Cache Hit)
```
#### Getting stakeholders for deal: Acme Corp Deal
[CACHE HIT] get-stakeholders took: 0.87 ms
```

### Third Call - Different Deal, Same Titles (Title Cache Hits)
```
#### Getting stakeholders for deal: Different Corp Deal
[PERFORMANCE] MongoDB query took: 38.42 ms
Found 8 unique stakeholders for deal Different Corp Deal
[PERFORMANCE] Stakeholder extraction took: 40.15 ms
[CACHE HIT] Title 'VP of Engineering' found in cache
[CACHE HIT] Title 'Software Engineer' found in cache
[CACHE HIT] Title 'Director of Product' found in cache
... (all from cache - no LLM calls!)
[PERFORMANCE] LLM analysis (parallel) took: 2.34 ms
[PERFORMANCE] ========================================
[PERFORMANCE] TOTAL get-stakeholders took: 53.89 ms (0.05 seconds)
[PERFORMANCE] Found 8 stakeholders for deal: Different Corp Deal
[PERFORMANCE] ========================================
```

## Performance Metrics Tracked

| Metric | Color | Description |
|--------|-------|-------------|
| **MongoDB query** | RED | Time to fetch buyer_attendees from database |
| **Stakeholder extraction** | RED | Time to deduplicate and extract unique stakeholders |
| **LLM analysis (parallel)** | RED | Time for all parallel LLM calls to complete |
| **TOTAL** | RED | End-to-end request time |
| **Cache hits (endpoint)** | GREEN | Entire response served from cache |
| **Cache hits (title)** | CYAN | Individual title analysis served from cache |
| **Cache miss (title)** | YELLOW | Title needs LLM analysis |

## Interpreting the Logs

### Slow MongoDB Query (> 100ms)
```
[PERFORMANCE] MongoDB query took: 342.18 ms  ⚠️ SLOW
```
**Possible causes:**
- No index on `deal_id` field
- Large number of meetings for this deal
- MongoDB server performance issues

**Fix:**
```python
# Check indexes
meeting_insights_repo.collection.list_indexes()

# Recreate index if needed
meeting_insights_repo.create_index({"deal_id": 1})
```

### Slow LLM Analysis (> 5000ms)
```
[PERFORMANCE] LLM analysis (parallel) took: 12843.21 ms  ⚠️ SLOW
```
**Possible causes:**
- OpenAI/LLM API is slow or rate-limited
- Many unique titles (no cache hits)
- Network latency

**What to check:**
- Are there many `[CACHE MISS]` logs? → First-time analysis, expected
- Are there mostly `[CACHE HIT]` logs but still slow? → LLM API issue
- Check OpenAI dashboard for API performance

### Fast Response with Cache
```
[CACHE HIT] get-stakeholders took: 0.87 ms  ✅ OPTIMAL
```
**This is perfect!** Endpoint-level cache working as expected.

### Fast Response with Title Cache
```
[PERFORMANCE] TOTAL get-stakeholders took: 53.89 ms (0.05 seconds)  ✅ GOOD
[CACHE HIT] Title 'VP of Engineering' found in cache
```
**This is great!** No LLM calls needed, just MongoDB query + cache lookups.

## Troubleshooting Guide

### If response is still very slow (> 10 seconds)

1. **Check which component is slow:**
   ```
   MongoDB query: XXX ms
   Stakeholder extraction: XXX ms
   LLM analysis: XXX ms    ← If this is > 10,000ms, read on
   ```

2. **If LLM analysis is slow:**
   - Check how many `[CACHE MISS]` logs appear
   - If many cache misses → This is the first time analyzing these titles (expected)
   - If few cache misses but still slow → LLM API is slow

3. **Check LLM model:**
   ```python
   # In llm_service.py line 39
   model="gpt-5"  # Is this model available? Check OpenAI status
   ```

4. **Check concurrent execution:**
   ```python
   # Look for these logs appearing at SAME time (parallel)
   [CACHE MISS] Analyzing title 'VP' via LLM
   [CACHE MISS] Analyzing title 'Director' via LLM
   [CACHE MISS] Analyzing title 'Engineer' via LLM

   # If they appear sequentially (one after another) → ThreadPoolExecutor not working
   ```

5. **Verify thread pool:**
   ```python
   # In hubspot_mongo.py line 875
   with ThreadPoolExecutor(max_workers=10) as executor:
   ```

### If MongoDB query is slow (> 100ms)

1. **Check indexes:**
   ```bash
   # In MongoDB shell or via Python
   db.meeting_insights.getIndexes()
   ```

2. **Check data size:**
   ```bash
   # How many meetings for this deal?
   db.meeting_insights.countDocuments({"deal_id": "YourDealName"})
   ```

3. **Verify projection is working:**
   - Should only fetch `buyer_attendees` field
   - Check MongoDB slow query log

## Expected Performance Targets

| Scenario | Target Time | Acceptable | Slow |
|----------|-------------|------------|------|
| **Endpoint cache hit** | < 1ms | < 5ms | > 10ms |
| **Title cache hits (no new LLM)** | < 100ms | < 500ms | > 1000ms |
| **First call (N stakeholders)** | < 2000ms | < 5000ms | > 10000ms |
| **MongoDB query** | < 50ms | < 100ms | > 200ms |

## Quick Diagnosis Commands

### Count cache entries
```python
# In Python REPL
from app.api.hubspot_mongo import _endpoint_cache
len(_endpoint_cache)  # How many cached items?

# Check specific cache keys
[k for k in _endpoint_cache.keys() if 'stakeholders' in k]
```

### Clear cache to test
```bash
# Via API
curl -X DELETE http://localhost:8000/api/hubspot-mongo/clear-endpoint-cache
```

### Monitor real-time
```bash
# Tail logs and filter for performance
tail -f your-app.log | grep "PERFORMANCE"
```
