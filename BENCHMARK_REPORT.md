# Benchmark & Observability Report — Day 14

**Họ tên:** BuiNgocVu
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11, Docker Desktop 29.7.2 (12 CPU, khoảng 7,6 GiB RAM cho Docker), Docker Compose v5.5.0. Phần 2–3 chạy trong container `python:3.11` (Linux); agent và load generator ở **cùng một container**, nên chúng chia nhau CPU.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Đường bình thường của mock LLM khoảng 190 ms, nên 500 ms còn dư địa cho dao động. Ngưỡng bắt được lúc quá tải (764 ms ở concurrency 100) và lúc hơn 5% request bị chậm |
| Error rate `/ask` | < 2 % | Mock LLM lỗi nền khoảng 1%, nên 2% cho phép dao động ngẫu nhiên. Với mẫu 300 request ngưỡng này vẫn khá sát (xem 2.2) |
| Accuracy trên golden dataset | ≥ 85 % | Trùng quality gate trong CI; v2 ban đầu đạt 91,3% |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request, `MOCK_SLOW_RATE` mặc định)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.56 | 190.4 | 221.1 | 1680.7 | 0.67% | PASS |
| 10 | 42.38 | 191.2 | 221.2 | 1706.4 | 2.00% | PASS (đúng bằng ngưỡng) |
| 50 | 113.69 | 200.3 | 253.4 | 1681.8 | 1.00% | PASS |
| 100 | 145.67 | 252.0 | 764.3 | 1722.4 | 1.67% | **FAIL** (p95) |

**Nhận xét:** RPS không tăng tuyến tính. Từ 1 lên 10, RPS tăng 9,3 lần (gần tuyến tính) vì thời gian chủ yếu là chờ LLM, và `async` cho phép chờ nhiều request cùng lúc. Từ 10 lên 50 (gấp 5 lần tải) RPS chỉ tăng 2,7 lần. Từ 50 lên 100 chỉ tăng 1,28 lần, trong khi p95 từ 253 ms lên 764 ms. Request bắt đầu xếp hàng chờ CPU: agent chỉ có 1 process, 1 event loop. Load generator chạy cùng container cũng góp phần, nên phép đo này không tách được hai nguyên nhân.

### 2.2 Tail latency (concurrency 20, 300 request)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190.8 | 218.7 | 228.6 |
| 0.03 (mặc định) | 226.5 | 223.3 | 1685.1 |
| 0.1 | 352.4 | 1695.1 | 1719.4 |

**Nhận xét:** Nhạy nhất là **p99**: chỉ 3% request chậm đã đẩy p99 từ 229 ms lên 1.685 ms, trong khi avg chỉ tăng khoảng 36 ms và p95 gần như không đổi. Khi tỉ lệ chậm lên 10% (vượt 5%), p95 mới nhảy lên 1.695 ms, còn avg mới tăng khoảng 162 ms so với mức 0. Không nên đặt SLO theo average vì nó trộn nhóm nhanh với nhóm chậm: avg 226 ms trông ổn, trong khi cứ 100 người thì hơn 1 người chờ gần 1,7 giây.

Lượt `MOCK_SLOW_RATE=0` có error rate 2,33% (7/300) nên `load_test.py` báo **FAIL** SLO lỗi. Đây là lỗi ngẫu nhiên của mock (`MOCK_ERROR_RATE=0.01`); mẫu 300 request quá nhỏ để ước lượng chính xác tỉ lệ 1%.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.7 | 108.8 | 113.7 |
| Tổng cost (USD) | 0.000412 | 0.000757 | 0.000791 |
| Cost / câu đúng (USD) | 0.00041235 | 0.00003607 | 0.00003440 |
| Quality gate | FAIL (≥80%) | PASS (≥80%, baseline v1) | PASS (≥100%, baseline v2) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | token, hết hạn, chữ ký | Thêm entry `["jwt"]` giải thích API key khác JWT: token có chữ ký số, có thời điểm hết hạn |
| `scaling-03` | cpu, memory, custom metrics | Thêm entry `["hpa", "kubernetes", "autoscal"]` mô tả HPA scale theo CPU, memory, custom metrics |

Sửa ở `develop/utils/mock_llm.py` và chép sang `production/utils/mock_llm.py`. Không sửa golden dataset. Eval cuối: 2 câu được cải thiện, **0 regression**. Thử gate ngược (v1 so với baseline v2): 20 regression, exit code 1.

**Nhận xét trade-off:** v2 tốn gấp khoảng 1,9 lần token mỗi câu và tổng cost cao hơn khoảng 1,8 lần, nhưng **cost / câu đúng rẻ hơn khoảng 11 lần** (0,000412 so với 0,000036). Chỉ số này tính cả giá của những câu trả lời sai, nên so sánh công bằng hơn cost / câu. Về latency, retrieval thêm khoảng 20 ms và prompt dài hơn cũng chậm hơn một chút. p95 trong report eval (v1 189 ms, v2 1.544 ms, v2 đã sửa 217 ms) **không dùng để so sánh**: chỉ có 23 mẫu, một hai request chậm ngẫu nhiên là p95 nhảy vọt.

---

## 4. Observability stack (production)

Baseline: 2 instance, 30 user Locust, mock-llm-small, cửa sổ 2 phút: 18,35 req/s, error 0,71%, p50 172 ms, p95 291 ms, p99 1.785 ms, avg 223 ms; req/s theo instance 9,23 và 9,12; token/s input 1.413, output 740; cost ước tính $2,36/giờ.

### 4.1 Screenshot

- [x] [Dashboard Grafana khi có tải](screenshots/grafana-dashboard.png)
- [x] [Trace chậm trong Jaeger](screenshots/jaeger-slow-trace.png)
- [x] [Trace lỗi, có event `exception`](screenshots/jaeger-error-trace.png)
- [x] [Trang Alerts với 2 alert cùng firing](screenshots/prometheus-alert-firing.png): `AgentHighErrorRate` và `LLMCostBurnRateHigh`

Ảnh được chụp bằng Edge headless (Playwright).

### 4.2 Thí nghiệm "phá hệ thống"

Thời gian được đo từ lúc chạy lệnh đổi cấu hình (`docker compose up -d agent` hoặc `docker pause`), poll `/api/v1/alerts` mỗi 3 giây. A, B, D, E chạy với 30 user; C chạy với 12 user.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel / số liệu phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | **84 s** (pending ở 24 s) | Error rate: 21,1% |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | **147 s** (pending ở 26 s) | Latency: p95 1,92 s, avg chỉ 0,63 s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **166 s** (pending ở 45 s) | Cost: $0,94/giờ → $10,08/giờ (đo sau khi firing 60 s); p95 0,30 s → 0,70 s |
| D | `docker pause` 1 instance | `AgentInstanceDown` | **42 s** (pending ở 15 s) | Instances up còn 1; error rate của agent 1,44% (gần mức nền); log Nginx có 22 dòng chứa 504 |
| E | `AGENT_VERSION=v1` | Không alert nào do thay đổi này (xem ghi chú) | — | Bảng version đổi sang v1; token/s khoảng 2.150 → 1.070; p95 còn 198 ms; retrieval hit ratio mất dữ liệu |

Thí nghiệm bổ sung để chụp ảnh: giữ model large và thêm `MOCK_ERROR_RATE=0.2` → `AgentHighErrorRate` firing sau **92 s**, cùng lúc với `LLMCostBurnRateHigh`.

**Ghi chú trung thực:**
- **Alert cost firing ngay ở baseline 30 user.** Model nhỏ đã tốn khoảng $2,36/giờ, vượt ngưỡng $2. Vì vậy với thí nghiệm C tôi hạ tải xuống 12 user, chờ alert về `inactive` (cost $0,94/giờ) rồi mới đổi model. Ngưỡng $2/giờ cần hiệu chỉnh theo lưu lượng thật, hoặc đổi sang alert theo cost mỗi request. Mức tăng khoảng 10,8 lần đo được thấp hơn con số "khoảng 16 lần" trong đề, vì cửa sổ 5 phút lúc đo còn lẫn dữ liệu model nhỏ và throughput cũng giảm.
- Trong thí nghiệm A, `AgentHighErrorRate` đi qua đủ `inactive → pending → firing`, rồi tắt sau 53 s kể từ khi khôi phục.
- Trong thí nghiệm E, `LLMCostBurnRateHigh` đang `pending` **từ trước khi đổi**, chuyển firing ở giây 27 rồi tự tắt khi cost giảm xuống $1,18/giờ. `AgentInstanceDown` pending thoáng qua ở giây 12 do container được tạo lại, không firing. Kết thúc 5,5 phút, không còn alert nào.
- Unit test alert rules: `promtool test rules` → `SUCCESS`.

**Thí nghiệm E không làm alert nào firing dù chất lượng giảm mạnh. Phát hiện bằng cách nào?**
Metric hạ tầng còn "đẹp hơn" (nhanh hơn, rẻ hơn) trong khi accuracy giảm từ 91% xuống 4% (số đo ở mục 3, trên bản develop). Cần giám sát chất lượng riêng: (1) eval trên golden dataset làm quality gate trong CI trước khi deploy; (2) chạy eval định kỳ trên bản đang chạy, đẩy accuracy thành metric và đặt alert; (3) chấm mẫu traffic thật (LLM-as-judge hoặc người chấm), thu feedback người dùng; (4) alert trên tín hiệu gián tiếp: retrieval hit ratio mất hoặc tụt, token/s đổi đột ngột, `agent_info` đổi version ngoài lịch deploy.

**Vì sao lỗi 504 không hiện trên metric của agent?** Instance bị pause không xử lý được request, nên không đếm được. Nginx chờ quá `proxy_read_timeout` 10 giây rồi trả 504. Metric chỉ phản ánh những gì chính service nhìn thấy, nên cần thêm metric ở load balancer hoặc synthetic check từ bên ngoài. Đây cũng là lý do dùng `pause` thay vì `stop`: container bị stop biến mất khỏi DNS, Prometheus bỏ luôn target nên không có `up == 0`.

### 4.3 Debug bằng trace

Trace chậm nhất trong số trace thành công lấy từ cửa sổ 5 phút (1.497 trace có `agent.run`):

- `trace_id`: `3ad22ace71fb15936ee1507b728b5876`
- Tổng thời gian: **1720.0 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1692.7 ms**, 98,4%). `agent.retrieve_context` chỉ 25.4 ms. Nguyên nhân là LLM upstream chậm, không phải code của agent.
- Dòng log tương ứng:

```json
{"ts": "2026-11-25T07:56:56.143755+00:00", "level": "INFO", "service": "observable-agent", "instance": "faa8f0d6fa08", "event": "llm_call", "trace_id": "3ad22ace71fb15936ee1507b728b5876", "span_id": "2a48903fee429d0b", "request_id": "5b725da68eb7", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1693.0}
```

Trace lỗi: `8e48b0888057f5f619e4bb022a801c64` (117.2 ms, HTTP 503). Span `chat mock-llm-small` (91.7 ms) có `error.type=upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError`).

```json
{"ts": "2026-11-25T07:56:40.487001+00:00", "level": "INFO", "service": "observable-agent", "instance": "faa8f0d6fa08", "event": "llm_error", "trace_id": "8e48b0888057f5f619e4bb022a801c64", "span_id": "d8cc1e9076e7c95b", "request_id": "55b56163942e", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

(Log của agent ghi `"level": "INFO"` cả với sự kiện lỗi vì `log_event` cố định level; nên sửa thành `ERROR` để lọc được.)

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10, 2 phút)

Số liệu lấy từ dòng `POST /ask` trong `benchmark-results/scale_*_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.12 | 190 | 240 | 1700 | 80 / 7144 (1.12%) |
| 3 | 60.12 | 190 | 220 | 1700 | 72 / 7141 (1.01%) |

Prometheus xác nhận số instance nhận traffic trong suốt mỗi lượt là 1 và 3. Ở lượt 3 instance, tải chia đều (khoảng 2.460, 2.392, 2.408 request theo `increase()`, cửa sổ gồm cả warm-up).

**Lưu ý về cách đo:** lệnh trong CP8 không có `--no-deps`. Với Compose v5.5.0, `docker compose run locust` đưa agent về lại `replicas: 2` (tạo/xoá container ngay lúc Locust khởi động). Hai lượt đầu vì vậy sai cấu hình; số liệu đó đã bị bỏ, và CSV nộp ở đây là của lượt chạy lại với `--no-deps`.

**Giải thích:** Scale từ 1 lên 3 gần như không đổi gì. RPS bằng nhau, p50 và p99 bằng nhau, p95 chỉ giảm 20 ms. Nút thắt **không nằm ở số instance**:
1. **Throughput bị giới hạn bởi load generator:** Locust là mô hình closed-loop. Mỗi user nghỉ 0,5–2 giây (trung bình 1,25 giây) giữa hai lần hỏi, nên 100 user chỉ tạo ra khoảng 65 req/s. Một instance đã đáp ứng đủ mức này.
2. **Latency do LLM quyết định:** p50 khoảng 190 ms và p99 khoảng 1,7 s (3% request bị chậm do `MOCK_SLOW_RATE`) là thời gian của LLM mock; thêm instance không làm một lần gọi LLM nhanh hơn. Mức giảm 20 ms ở p95 gợi ý 1 instance (giới hạn 0,5 CPU) có xếp hàng nhẹ, nhưng với một lượt đo mỗi cấu hình thì chưa đủ để kết luận.

Muốn thấy lợi ích của scale cần tăng tải đến khi 1 instance bão hoà. Muốn giảm p99 cần xử lý phía LLM: timeout và retry có chọn lọc, hedged request, cache hoặc đổi model.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. Phải xem percentile: 3% request chậm gần như không lộ ra ở avg và p95, chỉ p99 cho thấy.
  2. Phải kiểm chứng **điều kiện đo** trước khi tin số đo: hai lượt scale đầu chạy xong không báo lỗi gì nhưng thực chất đều không đúng số instance.
  3. Dashboard xanh không có nghĩa là agent đúng: đổi sang v1 làm hạ tầng "tốt lên" trong khi chất lượng sụp. Cần cả eval và metrics, trace, log.
- Nếu đưa lên production thật, tôi sẽ thêm:
  - Metric và alert ở **load balancer** (5xx, 504, latency nhìn từ client) và synthetic check từ bên ngoài.
  - Alert p99, hoặc SLO theo **burn rate** của error budget, thay cho ngưỡng tức thời.
  - Alert **cost mỗi request** và ngân sách ngày, thay cho ngưỡng $/giờ cố định không phụ thuộc lưu lượng.
  - Metric chất lượng: accuracy của eval định kỳ, retrieval hit ratio, tỉ lệ feedback xấu.
  - Alert khi số instance đang chạy thấp hơn số mong muốn (bắt được cả trường hợp container bị stop hẳn).

---

## Bằng chứng

- `reports/`: JSON của 7 lượt load test và 3 lượt eval
- `benchmark-results/`: CSV của Locust
- `screenshots/`: Grafana, Jaeger (2 ảnh), Prometheus Alerts
