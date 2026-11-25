# Deployment Information

## Public URL

https://day14-agent-production.up.railway.app

## Platform

Railway: project `day14-agent`, gồm service `day14-agent` (build từ `06-lab-complete/Dockerfile`) và database Redis.

## Kết quả kiểm tra ngày 2026-11-25

| Lệnh | Mã HTTP |
|---|---|
| `GET /health` | 200 |
| `GET /ready` | 200 |
| `POST /ask` không có key | 401 |
| `POST /ask` có key | 200 |

- Rate limit: gửi tiếp 12 request cùng key thì 9 request đầu trả 200 (đủ 10 request trong 60 giây), 3 request sau trả **429**.
- `python check_production_ready.py --static-only --public-url https://day14-agent-production.up.railway.app`: mục Public URL → 200.

## Cách deploy

### Cách A: Railway

```bash
npm i -g @railway/cli
cd 06-lab-complete
railway login
railway init
railway add --database redis        # tạo Redis trong project
railway up                          # lần đầu sẽ tạo service cho agent
```

Trong dashboard, ở service agent, mục **Variables**:

- `AGENT_API_KEY`: tạo bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `REDIS_URL`: tham chiếu tới Redis, `${{Redis.REDIS_URL}}` (đổi `Redis` theo đúng tên service Redis)
- `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`

Sau đó `railway up` lại, rồi `railway domain` để lấy URL.

### Cách B: Render

1. Commit và push repo lên GitHub.
2. Render Dashboard → New → Blueprint → chọn repo, đặt **Blueprint Path** là `06-lab-complete/render.yaml`.
3. `AGENT_API_KEY` được tự sinh, `REDIS_URL` tự nối tới Key Value `day14-redis`. Copy key trong tab Environment để test.

Bài này deploy bằng Cách A. `render.yaml` mới được kiểm tra bằng script chấm, chưa chạy thử trên Render.

## Test Commands

Đặt `BASE` là URL public, `AGENT_API_KEY` là key đã đặt trên nền tảng. Mỗi lệnh chỉ in mã HTTP.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # mong đợi 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # mong đợi 200
```

## Environment Variables Set

Đặt trên nền tảng, không ghi giá trị vào repo:

- `AGENT_API_KEY`
- `REDIS_URL`
- `ENVIRONMENT`
- `LOG_LEVEL`
- `RATE_LIMIT_PER_MINUTE`
- `DAILY_BUDGET_USD`
- `PORT` (nền tảng tự cấp)

## Screenshots

Ảnh cần có (đúng tên):

- `screenshots/dashboard.png`: dashboard của nền tảng
- `screenshots/running.png`: service đang chạy
- `screenshots/test.png`: kết quả 4 lệnh test (không để lộ key)
