# Day 14 Lab - Mission Answers

**Môi trường đo:** Windows 11 + Docker Desktop 29.7.2 (12 CPU, khoảng 7,6 GiB cho Docker). Python chạy trong container `python:3.11` (Linux, `os.name = posix`), không dùng WSL2 hay Python Windows.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret** (dòng 17–18): `OPENAI_API_KEY` và `DATABASE_URL` kèm mật khẩu nằm trong code. Push lên repo public là lộ, và xoá file sau đó vẫn còn trong lịch sử git.
2. **Log ra secret** (dòng 34): in `OPENAI_API_KEY` ra stdout. Ai đọc được log là đọc được key.
3. **Không có config management** (dòng 21–22): `DEBUG`, `MAX_TOKENS` cố định, muốn đổi phải sửa code.
4. **Dùng `print()` thay logging** (dòng 33–38): không có level, timestamp, định dạng máy đọc được. Còn in cả nội dung câu hỏi.
5. **Không có health check:** nền tảng không biết khi nào cần restart hay ngừng route traffic.
6. **Bind `localhost`** (dòng 51): trong container thì bên ngoài không gọi vào được.
7. **Port cố định 8000** (dòng 52): bỏ qua biến `PORT` mà Railway/Render cấp.
8. **`reload=True`** (dòng 53): chế độ dev, tốn tài nguyên và thêm một process cha trung gian khi nhận signal.
9. **Không validate input / xử lý lỗi:** `question` không giới hạn độ dài.

### Exercise 1.2: Chạy bản develop

```text
POST /ask?question=Hello          → HTTP 200 {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
POST /ask  (JSON body)            → HTTP 422 {"detail":[{"type":"missing","loc":["query","question"],...}]}
GET  /health                      → HTTP 404

# log của server
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this      <-- secret bị lộ (key giả có sẵn trong đề)
```

Bản này chạy được nhưng chưa sẵn sàng cho production. App nhận `question` qua query nên gửi JSON bị 422.

### Exercise 1.3: So sánh develop và production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hằng số trong code | `config.py` đọc env, có `validate()` | Cùng một code chạy ở dev/staging/prod; fail fast khi production thiếu `AGENT_API_KEY` |
| Secrets | Hardcode và log ra | `os.getenv`, chỉ commit `.env.example` | Không lộ key qua git hoặc log; xoay key không cần sửa code |
| Port / host | `localhost:8000` | `HOST=0.0.0.0`, `PORT` từ env (`app.py` dòng 194–197) | Chạy được trong container và trên nền tảng tự cấp port |
| Health check | Không có | `GET /health` (dòng 135), `GET /ready` (dòng 152) | Liveness để restart, readiness để ngừng route traffic |
| Logging | `print()` | `logging` + `json.dumps`, chỉ log độ dài câu hỏi | Lọc, tìm kiếm được; không lộ nội dung hay secret |
| Shutdown | Tắt đột ngột | `lifespan` + handler SIGTERM | Hoàn thành request đang chạy, đóng kết nối |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Giới hạn được origin (mặc định `*` vẫn cần siết lại) |
| Reload | Luôn bật | Chỉ bật khi `DEBUG=true` | Không chạy chế độ dev ở production |

**Kết quả chạy bản production:** `/health` 200, `/ready` 200, `POST /ask` (JSON) 200. Gửi SIGTERM thì thoát với exit code 0.

**Một điểm tôi thấy khi chạy:** các dòng log JSON của bản production **không xuất hiện**. `config.py` gọi `logging.warning()` ngay lúc import (trong `validate()`), làm root logger được cấu hình mặc định trước. Vì vậy `basicConfig()` trong `app.py` không còn tác dụng và log mức INFO bị ẩn. Ở Part 6 tôi dùng logger riêng có handler và formatter của nó.

## Part 2: Docker

### Exercise 2.1: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản đầy đủ).
2. **Working directory:** `/app`.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo layer. Khi chỉ sửa code, layer `pip install` được dùng lại. Nếu copy code trước, sửa một dòng cũng phải cài lại toàn bộ dependencies.
4. **CMD và ENTRYPOINT:** `CMD` là lệnh hoặc tham số mặc định, bị thay thế khi truyền lệnh vào `docker run image <lệnh>`. `ENTRYPOINT` là chương trình cố định; tham số của `docker run` được nối thêm vào sau, chỉ đổi được bằng `--entrypoint`. Khi dùng cả hai thì `CMD` là tham số mặc định cho `ENTRYPOINT`.

### Exercise 2.2: Build và chạy bản develop

Build từ gốc repo. `POST /ask?question=Docker` → 200 `{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`; `GET /health` → 200.

### Exercise 2.3: Kích thước image

| Image | `docker images` (dung lượng trên đĩa) | `docker image inspect .Size` (nén) |
|---|---|---|
| `my-agent:develop` | **1,67 GB** | 426.320.068 bytes |
| `my-agent:advanced` | **240 MB** | 57.409.097 bytes |
| Chênh lệch | **nhỏ hơn khoảng 85,6%** | nhỏ hơn khoảng 86,5% |

Hai cột khác nhau vì Docker máy này dùng containerd image store.

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev`, rồi `pip install --user` vào `/root/.local`.
- **Stage 2 (`runtime`):** bắt đầu từ `python:3.11-slim` sạch, chỉ copy `/root/.local`, `main.py`, `utils/`; tạo user non-root, thêm `HEALTHCHECK`.
- **Vì sao nhỏ hơn:** compiler, header và apt cache nằm lại ở stage builder. Ngoài ra base `slim` nhỏ hơn nhiều so với `python:3.11`, nên phần chênh lệch so với bản develop đến từ cả hai yếu tố.

### Exercise 2.4: Docker Compose stack

```text
Client ──:80──▶ nginx ──▶ agent:8000 ──depends_on──▶ redis:6379   (healthy)
                (reverse proxy,          └─────────▶ qdrant:6333  (healthy)
                 limit 10 r/s, burst 20)
                              network nội bộ "internal"; chỉ nginx mở port ra host (80, 443)
```

4 service được start: `agent`, `redis`, `qdrant`, `nginx`. Chúng gọi nhau bằng tên service qua DNS của Docker. `agent` chờ `redis` và `qdrant` healthy mới khởi động.

Test qua Nginx:

```text
GET  /health → 200 {"status":"ok","version":"2.0.0",...}   (header Server: nginx, X-Frame-Options: DENY)
POST /ask    → 200 {"answer":"Đây là câu trả lời từ AI agent (mock)..."}
```

Quan sát thêm:
- `main.py` chưa thực sự dùng Redis hay Qdrant; compose chỉ khai báo sẵn `REDIS_URL`, `QDRANT_URL`.
- Comment trong compose ghi "2 replicas" nhưng thực tế chỉ có 1 agent. Port 443 được mở nhưng `nginx.conf` chỉ `listen 80`.
- Dòng log JSON của app bị hỏng: `{"time":...,"msg":"{"event": "request", "q_len": 21}"}`. Chuỗi JSON lồng trong `msg` không được escape. Cách đúng là dùng formatter gọi `json.dumps` cho cả record.

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- **Nền tảng:** Railway (service `day14-agent` + database Redis). Chi tiết ở [DEPLOYMENT.md](DEPLOYMENT.md).
- **URL:** https://day14-agent-production.up.railway.app
- **Kiểm tra:** `/health` 200, `/ready` 200, `/ask` không key 401, có key 200; vượt 10 request/phút → 429.
- **Biến môi trường** đặt trên Railway: `AGENT_API_KEY` (sinh ngẫu nhiên, không ghi vào repo), `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT`, `LOG_LEVEL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`.
- **Screenshot:** [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)
- **Lưu ý:** Railway CLI cảnh báo config-as-code (`railway.toml`) đã bị đánh dấu deprecated, file hiện có còn dùng được tới 2026-12-01.

### So sánh `railway.toml` và `render.yaml`

| Điểm | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Cách build và chạy **một** service | Blueprint cho **nhiều** tài nguyên: web service và Key Value (Redis) |
| Định dạng | TOML, mục `[build]`, `[deploy]` | YAML, danh sách `services` |
| Build | `builder = "DOCKERFILE"` (mẫu của đề dùng `NIXPACKS`) | `runtime: docker` + `dockerfilePath`, `rootDir` (mẫu dùng `runtime: python` + `buildCommand`) |
| Health check | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` |
| Restart | `restartPolicyType`, `restartPolicyMaxRetries` | Nền tảng tự quản lý |
| Biến môi trường | Không khai báo trong file; đặt bằng CLI hoặc dashboard | `envVars`; secret dùng `generateValue: true` hoặc `sync: false` |
| Redis | Tạo riêng trên dashboard, rồi đặt `REDIS_URL` | Khai báo trong file, nối bằng `fromService.connectionString` |
| Region / plan | Chọn trên dashboard | Khai báo được (`region`, `plan`) |

Lý do khác nhau: `render.yaml` là Infrastructure as Code, mô tả cả hạ tầng để tạo một lần. `railway.toml` chỉ là config-as-code cho từng service, còn hạ tầng được quản lý trên project Railway.

### Exercise 3.3: Pipeline Cloud Run

`cloudbuild.yaml` chạy tuần tự qua `waitFor`: (1) **test** bằng `pytest` trong `python:3.11-slim` → (2) **build** image gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` → (3) **push** lên Container Registry → (4) **deploy** Cloud Run ở `asia-southeast1`, 1–10 instance, 512 MiB, secret lấy từ Secret Manager. Bước trước fail thì các bước sau không chạy.
`service.yaml` mô tả service theo chuẩn Knative: `containerConcurrency: 80`, timeout 60 giây, giới hạn CPU/RAM, `startupProbe` gọi `/ready`, `livenessProbe` gọi `/health`.
Hai điểm cần sửa trước khi dùng thật: step test trỏ tới `tests/`; step deploy chỉ set secret `OPENAI_API_KEY`, trong khi `service.yaml` còn cần `AGENT_API_KEY`.

## Part 4: API Security

### Exercise 4.1: API key (bản develop, chạy với `AGENT_API_KEY=secret-key-123` là key mẫu của đề)

- **Check ở đâu:** dependency `verify_api_key` (`develop/app.py` dòng 39–54), gắn vào `/ask` bằng `Depends`.
- **Sai key:** thiếu key → 401; sai key → **403**. (Agent Part 6 trả 401 cho cả hai, theo yêu cầu của script chấm.)
- **Rotate key:** đổi biến môi trường `AGENT_API_KEY` rồi restart/redeploy. Muốn không gián đoạn thì cho phép tạm 2 key (cũ và mới) trong thời gian chuyển đổi.

```text
# không có key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# đúng key
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT

Luồng: `POST /auth/token` (`student` / `demo123`) → server ký JWT HS256 chứa `sub`, `role`, `iat`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → server verify chữ ký và hạn dùng, không cần tra database. Token sai chữ ký → 403, hết hạn → 401. `JWT_SECRET` đang có giá trị mặc định trong code, production phải đặt qua env.

```text
# POST /ask không token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# lấy token thành công: <TOKEN ĐÃ CHE> (dài 168 ký tự)
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window. Mỗi user có một `deque` lưu timestamp, tức là dạng *sliding window log* (docstring gọi là "Sliding Window Counter").
- **Giới hạn:** user 10 req/phút, admin 100 req/phút.
- **"Bypass" cho admin:** không bỏ qua hẳn. `app.py` chọn `rate_limiter_admin` khi `role == "admin"` (tài khoản `teacher`).
- **Hạn chế:** state nằm trong RAM. Nhiều instance thì mỗi instance đếm riêng, restart là mất.

Vòng lặp 20 request bằng token của `student`: request 1–10 trả 200, **11–20 trả 429**.

```text
req 1
HTTP/1.1 200 OK
{"question":"Test 1","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

req 11
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Lỗi nhỏ trong code mẫu: field `budget_remaining_usd` thực ra trả **chi phí đã dùng** (`app.py` dòng 160). `GET /me/usage` mới đúng: `cost_usd 0.000181`, `budget_remaining_usd 0.999819`.

### Exercise 4.4: Cost guard

Rate limit bảo vệ **tốc độ**, cost guard bảo vệ **tiền**. User đi đúng giới hạn 10 req/phút vẫn có thể tốn rất nhiều nếu chạy liên tục cả ngày hoặc dùng prompt dài, nên cần cả hai.

Yêu cầu của đề: $10/tháng/user, lưu trong Redis, reset đầu tháng. Solution mẫu làm `GET` rồi mới `INCRBYFLOAT`, nên hai request song song có thể cùng thấy còn ngân sách. Tôi gộp thành một Lua script:

```python
_RESERVE = r.register_script("""
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
if spent + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 32 * 24 * 3600)
return 1
""")

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return bool(_RESERVE(keys=[f"budget:{user_id}:{month}"],
                         args=[estimated_cost, MONTHLY_BUDGET_USD]))
```

Key có tháng (`YYYY-MM`) nên sang tháng mới tự reset; `EXPIRE` dọn key cũ. Đã kiểm thử với Redis thật: chặn khi vượt, cho qua khi bằng đúng 10, budget tách theo user, và 200 lời gọi song song mức 1 USD chỉ có đúng 10 lời được nhận.

**Trong agent Part 6** (`app/cost_guard.py`): ngân sách theo **ngày** (`DAILY_BUDGET_USD`), chung cho cả service. `check_budget()` trước khi gọi LLM (402 khi đã hết), `record_cost()` sau khi gọi, dùng `INCRBYFLOAT`. Giới hạn đã biết: các request song song lúc gần hết ngân sách có thể làm tổng vượt nhẹ. Redis chết thì `/ask` trả 503 (fail closed).

## Part 5: Scaling & Reliability

### Exercise 5.1: Health và readiness

```text
GET /health → 200 {"status":"ok","uptime_seconds":3.8,...,"checks":{"memory":{"status":"ok","used_percent":17.2}}}
GET /ready  → 200 {"ready":true,"in_flight_requests":1}
```

- **`/health` (liveness):** process còn sống không. Fail thì nền tảng **restart**. Không nên phụ thuộc Redis, nếu không Redis chết sẽ làm toàn bộ agent bị restart liên tục mà không sửa được gì.
- **`/ready` (readiness):** có nhận traffic được không. Fail (503) thì load balancer **ngừng route**, không restart.
- `in_flight_requests` bằng 1 vì tính cả chính request `/ready`.

### Exercise 5.2: Graceful shutdown

Gửi request mất khoảng 3 giây, 0,5 giây sau gửi SIGTERM:

```text
SIGTERM sent
request 1: HTTP 200 after 3.025222s
server exit code: 0

INFO:     Shutting down
INFO:     "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
```

Request đang chạy vẫn hoàn thành. Dòng log `Received signal 15` xuất hiện **cuối cùng** vì uvicorn bắt signal trước rồi mới gọi lại handler của app sau khi tắt xong.

### Exercise 5.3: Stateless

Lưu history trong RAM thì request sau có thể rơi vào instance khác và không thấy history; restart cũng mất. Bản production lưu `session:<id>` trong Redis với TTL 1 giờ. Hai điểm còn yếu:
1. Redis không kết nối được lúc khởi động thì app **âm thầm** chuyển sang dict trong RAM, mất tính stateless.
2. `append_to_history` làm đọc → sửa → ghi, nên hai request song song cùng session có thể ghi đè nhau. Dùng `RPUSH` + `LTRIM` sẽ an toàn hơn.

### Exercise 5.4: Load balancing

`docker compose -p k5-day14-scaling up -d --build --scale agent=3`: 3 agent healthy sau Nginx (port 8080). Nginx dùng DNS của Docker để phân phối.

### Exercise 5.5: Test stateless

`python test_stateless.py`: 5 request được phục vụ bởi **3 instance** (`instance-1d2fd4`, `instance-72da6b`, `instance-faa702`), history đủ **10 message**.

Script không tự tắt instance nên tôi thử thêm: tạo session mới, `docker stop` `agent-1`, rồi gửi tiếp 6 request cùng session:

```text
HTTP 200 instance-faa702 turn 3
HTTP 200 instance-faa702 turn 4
HTTP 200 instance-1d2fd4 turn 5
HTTP 200 instance-faa702 turn 6
HTTP 200 instance-1d2fd4 turn 7
HTTP 200 instance-faa702 turn 8
history count: 14
```

Không request nào lỗi và history còn nguyên vì state nằm trong Redis.

## Part 6: Output `check_production_ready.py`

Chạy bản đầy đủ (có Docker) trong container Linux: **43/43 checks passed**, image `docker image inspect` = 56 MB.

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Quyết định thiết kế chính:
- `/health` không đụng Redis; `/ready` ping Redis (503 khi mất).
- Rate limit dùng sorted set trong một **Lua script** để 2 worker không cùng lách qua giới hạn; key Redis chứa hash của API key.
- So sánh API key bằng `hmac.compare_digest`; `AGENT_API_KEY` rỗng thì từ chối tất cả.
- Input sai → 422; Redis lỗi → 503; lỗi không lường trước → 500 chung chung, stack trace chỉ ghi vào log.
- Không tự đăng ký SIGTERM handler; dùng `lifespan` và cơ chế tắt của uvicorn (`--timeout-graceful-shutdown 8`).

## Part 7: Câu hỏi Exercise 7.1–7.6

Số liệu benchmark và alert nằm trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

### 7.1: Metrics

1. **Counter:** `http_requests_total`, `llm_tokens_total`. **Gauge:** `agent_in_flight_requests`, `agent_info`. **Histogram:** `http_request_duration_seconds`, `llm_request_duration_seconds`.
2. Nếu dùng URL thật làm label, mỗi URL lạ (`/wp-admin`, `/.env`, ...) tạo thêm một bộ time series (với histogram là hàng chục series mỗi URL). Bot quét có thể làm Prometheus hết RAM. Khi thử gọi `/wp-admin` và `/a1b2c3`, cả hai được gộp vào `route="unmatched"` (đếm 2.0).

Metric mới `agent_question_length_chars` (Histogram) đã thêm vào `develop/app.py`. Sau lượt eval: `_count 23`, `_sum 1066`, bucket `le=20`: 1, `le=50`: 16, `le=100`: 23.

### 7.3: Quality gate trong CI

Job ở [.github/workflows/eval.yml](.github/workflows/eval.yml). `run_eval.py` trả **exit code 1** khi accuracy thấp hơn `--min-accuracy` hoặc có regression so với baseline, làm job fail. Muốn chặn merge phải bật branch protection và đặt check này là *Required*. Đã thử trên máy: eval v1 với baseline v2 cho 20 regression, FAIL, exit 1. Workflow chưa được chạy trên GitHub Actions.

### 7.4: Observability stack (2 instance, 30 user Locust, cửa sổ 2 phút)

1. **p95 = 291 ms, avg = 223 ms** (p50 = 172 ms, p99 = 1.785 ms). p95 gần avg, nhưng p99 gấp khoảng 8 lần avg: có một nhóm nhỏ (khoảng 3%, `MOCK_SLOW_RATE`) bị chậm hẳn mà avg che mất. p95 trong Prometheus là giá trị nội suy trong bucket histogram, nên cao hơn p95 Locust đo được (khoảng 220–240 ms ở lượt 100 user).
2. Nginx chia đều: **9,23 và 9,12 req/s** cho 2 instance.
3. Input **1.413 token/s**, output **740 token/s**: mỗi prompt gồm system prompt, tài liệu retrieval và câu hỏi, còn câu trả lời chỉ là đoạn tài liệu.
4. `curl http://localhost:8080/metrics` → **404**: Nginx chặn chủ đích, vì metrics lộ route, lưu lượng và chi phí. Prometheus scrape thẳng từng container trong mạng nội bộ.

### 7.5: Tracing

Xem mục 4.3 của [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

## Lỗi trong repo đề mà tôi phải xử lý

1. `06-lab-complete/benchmark-observability/production/Dockerfile`: container crash liên tục `ModuleNotFoundError: No module named 'uvicorn'`. User có home `/app` nhưng package nằm ở `/home/agent/.local`. Đã thêm `ENV PYTHONUSERBASE=/home/agent/.local`.
2. Lệnh benchmark scale ở CP8 (với Docker Compose v5.5.0): `docker compose run locust` đưa số agent về lại `deploy.replicas: 2`. Hai lượt đo đầu của tôi vì vậy đều sai số instance (event cho thấy `agent-3` bị destroy đúng lúc Locust start). Tôi **bỏ số liệu đó**, chạy lại với `--no-deps`, và xác nhận số instance nhận traffic bằng Prometheus.

## AI log

| Mục | Nội dung |
|---|---|
| Công cụ | Claude Code (model Claude Sonnet 5.5) |
| Hỏi gì | "đọc tất cả các file MD và hoàn thiện bài lab cho tôi"; "deploy hộ tôi được không?"; nhờ đối chiếu bài với `SUBMISSION.md`, đổi tên ảnh, sửa lệnh test lỗi trong PowerShell và điền AI log |
| AI đã làm | Viết code trong `06-lab-complete/app/`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`; thêm metric và 2 entry knowledge base; sửa Dockerfile của stack Part 7; viết workflow CI; deploy agent lên Railway bằng CLI (học viên đăng nhập trên trình duyệt) và chạy kiểm tra trên URL thật; **chạy toàn bộ lệnh đo**, tạo report JSON/CSV; chụp ảnh Grafana/Jaeger/Prometheus bằng Edge headless (Playwright); đổi tên, chuyển định dạng và lưu 3 ảnh deploy do học viên chụp; đưa lệnh test bản PowerShell; soạn nội dung mục AI log này; soạn `MISSION_ANSWERS.md`, `DEPLOYMENT.md`, `BENCHMARK_REPORT.md` |
| AI kiểm tra thế nào | `check_production_ready.py` bản đầy đủ; `promtool test rules`; chạy thật từng bài tập; đối chiếu số trong báo cáo với file JSON/CSV |
| Không sửa | `check_production_ready.py`, `golden_dataset.jsonl` |
| Học viên tự sửa và tự kiểm tra | **Tự kiểm tra:** đăng nhập Railway trên trình duyệt và cấp quyền cho CLI; tự chạy 4 lệnh trên URL public bằng PowerShell, nhận 200 / 200 / 401 / 200 (lần đầu chạy khối lệnh Git Bash trong PowerShell nên lỗi, hỏi lại AI rồi chạy bản PowerShell); mở `/ready` trên trình duyệt thấy `{"status":"ready"}`; kiểm tra trên dashboard Railway thấy agent và Redis Online; tự chụp 3 ảnh deploy (`dashboard`, `running`, `test`). **Tự sửa:** chưa tự sửa code hay câu trả lời nào do AI viết. |
