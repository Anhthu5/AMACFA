# Kiến trúc và hướng dẫn triển khai

AMACFA kiểm tra một lô hóa đơn AP theo bộ kiểm soát nội bộ `AP-DEMO-1.0`. Mỗi hồ sơ đi qua bốn Agent có nhiệm vụ riêng và một bước duyệt có checkpoint. Ba Agent đầu dùng công cụ xác định được kết quả từ cùng dữ liệu và chính sách. Agent báo cáo có thể dùng LLM để ưu tiên việc xác minh.

## Tech stack và lựa chọn

| Thành phần | Tích hợp trong repo | Lựa chọn khi mở rộng |
| --- | --- | --- |
| Điều phối | **LangGraph** với `StateGraph`, checkpoint SQLite và `interrupt()` | **CrewAI** là một lựa chọn điều phối theo vai trò cần adapter riêng. StateGraph phù hợp với yêu cầu nhìn thấy điều kiện rẽ nhánh, tạm dừng và resume theo mã hồ sơ. |
| Dịch vụ | **Python 3.13**, **FastAPI**, Pydantic, Uvicorn | Chuyển xử lý lô lớn sang hàng đợi và worker độc lập. |
| Vector DB | **Chroma** lưu các đoạn điều khoản có phiên bản trên đĩa. Mặc định dùng chỉ mục trong bộ nhớ với cùng tập vector. | **Pinecone** là phương án DB vector được quản lý. Nếu chuyển, giữ phạm vi phiên bản, hợp đồng xếp hạng và ánh xạ điều khoản chính. |
| GraphRAG | **Neo4j** truy vấn quan hệ nhà cung cấp, hóa đơn và token tài khoản bằng Cypher tham số hóa. Quan hệ truy hồi trở thành bằng chứng trong gói kiểm toán. Chế độ mặc định dùng nhóm quan hệ Python. | Mở rộng đến đồ thị nhà cung cấp, PO và thanh toán khi khóa nguồn và phạm vi truy cập đã được chuẩn hóa. |
| LLM | **GPT-4o** qua OpenAI Responses API, **Claude Sonnet 4.6** qua Anthropic Messages API, hoặc xếp hạng offline. | Cấu hình ID model qua `AMACFA_LLM_MODEL`. Anthropic đã ngừng Claude 3.5 Sonnet ngày 28/10/2025. |
| Kiểm thử | pytest, Ruff, fixture có nhãn, mock HTTP của hai SDK, test tích hợp với Neo4j và Chroma | CI trong `.github/workflows/ci.yml` chạy trên Ubuntu có Neo4j service. |

Nguồn tham chiếu [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [CrewAI](https://docs.crewai.com/en/introduction), [Chroma Query and Get](https://docs.trychroma.com/docs/querying-collections/query-and-get), [Pinecone semantic search](https://docs.pinecone.io/guides/search/semantic-search), [Neo4j Python driver](https://neo4j.com/docs/python-manual/current/query-simple/), [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o), [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [vòng đời model Anthropic](https://docs.anthropic.com/en/docs/about-claude/model-deprecations).

## Hợp đồng giữa các Agent

| Bước | Nhận | Thao tác và đầu ra |
| --- | --- | --- |
| Data Ingestion Agent | Hóa đơn đã qua parser CSV và SHA-256 của tệp | Xác minh hash từng hóa đơn chuẩn hóa trước khi bàn giao. Giữ số dòng vật lý để truy ngược tệp. |
| Forensic Agent | Các dòng bằng chứng và hạn mức theo tiền tệ | Tìm số hóa đơn trùng theo cùng nhà cung cấp, thiếu phê duyệt ở ngưỡng, tự phê duyệt, khả năng chia nhỏ và quan hệ dùng chung tài khoản. Đầu ra gồm quy tắc, dòng nguồn và chỉ số. |
| Compliance Agent | Tín hiệu và catalog đã định phiên bản | Gắn điều khoản chính bằng ánh xạ cố định, thêm điều khoản tham khảo qua vector search và tạo SHA-256 của gói bằng chứng. |
| Reviewer | Gói bằng chứng và mã băm từ checkpoint | `approve` mở bước báo cáo. `return` đóng hồ sơ để analyst kiểm tra và gửi một hồ sơ mới. Review receipt lưu vai trò, quyết định, ghi chú, thời gian UTC và mã băm gói. |
| Executive Reporting Agent | Gói và biên nhận phê duyệt | Kiểm lại hash, xếp hạng tối đa ba việc ưu tiên và dựng báo cáo tiếng Việt từ dữ liệu đã duyệt. Trả Markdown, SHA-256 tệp và nguồn xếp hạng. |

CSV dùng UTF-8, dòng đầu là tên cột. Xem [CSV có nhãn](../data/invoices_mixed.csv) để lấy đúng schema. Ngày theo `YYYY-MM-DD`, số tiền là Decimal dương. USD/EUR chấp nhận tối đa hai chữ số thập phân, VND dùng số nguyên. Hai trường `approved_by` và `account_token` có thể trống. Token tài khoản là mã tham chiếu đã được tạo ở hệ thống nguồn. Dữ liệu mặc định giới hạn 1 MiB và 1.000 hóa đơn. Các mã được chuẩn hóa NFKC, loại bỏ khoảng trắng hai đầu và viết hoa.

Hạn mức mẫu là USD 10.000, EUR 9.000 và VND 250.000.000. Quy tắc chia nhỏ nhóm các hóa đơn dưới ngưỡng theo nhà cung cấp, người đề nghị và tiền tệ. Thuật toán quét theo ngày, phát tín hiệu tại lần đầu tổng đạt hạn mức trong một cửa sổ bảy ngày, rồi bắt đầu nhóm tiếp theo. Các số hóa đơn đã bị đánh dấu trùng được loại khỏi phép cộng. Tín hiệu dùng chung tài khoản xét các mã nhà cung cấp khác nhau trong cùng một lô và có thể bao gồm trường hợp hợp lệ, ví dụ đại lý thu hộ.

## Truy xuất và quyền hạn của LLM

Neo4j truy xuất cạnh theo `audit_id` để chỉ nhận bằng chứng thuộc hồ sơ đó. Catalog chính sách đi vào Chroma qua vector băm từ khóa cục bộ. Cách mã hóa này phù hợp cho demo offline và chủ yếu đo mức trùng từ. Muốn đánh giá truy hồi ngữ nghĩa đa ngôn ngữ, có thể thay bộ mã hóa và đánh giá lại độ liên quan trên tập truy vấn có nhãn.

Chỉ sau khi duyệt, LLM có thể nhận tối đa 20 ứng viên, mỗi ứng viên gồm ID phát hiện, mã quy tắc, mức độ và mã kiểm soát. SDK dùng structured output cho danh sách ID. Bộ xác thực kiểm tra ID tồn tại, duy nhất và giữ thứ tự mức độ cao trước trung bình. Khi nhà cung cấp lỗi, từ chối hoặc trả dữ liệu sai, hệ thống ghi nguồn `fallback` và dùng cùng thứ tự xác định như demo offline. Nội dung và đề xuất hành động trong báo cáo đến từ catalog, dòng bằng chứng và mẫu báo cáo.

## Gọi HTTP

| Endpoint | Vai trò | Đầu vào và kết quả |
| --- | --- | --- |
| `GET /healthz` | Công khai | Trạng thái tiến trình sau khi khởi tạo. |
| `POST /audits` | Analyst | `Content-Type: text/csv`, UUID trong `Idempotency-Key`. Trả hồ sơ và gói chờ duyệt. Gửi lại đúng bytes và UUID để lấy hồ sơ cũ hoặc tiếp tục bước thu thập bằng chứng bị gián đoạn. |
| `GET /audits/{audit_id}` | Analyst hoặc Reviewer | Trạng thái, gói bằng chứng, sự kiện theo Agent, quyết định và báo cáo nếu đã xuất. |
| `POST /audits/{audit_id}/review` | Reviewer | Header `X-Review-Packet-SHA256` lấy từ `packet_sha256` và JSON gồm `decision`, `note`. Gửi lại đúng nội dung để lấy quyết định đã lưu hoặc tiếp tục bước báo cáo. |
| `GET /audits/{audit_id}/report.md` | Analyst hoặc Reviewer | Tải Markdown khi trạng thái là `completed`. Trước đó API trả HTTP 409. |

Mã lỗi thường gặp gồm 401 cho token thiếu hoặc sai, 403 cho sai vai trò, 409 cho xung đột trạng thái hoặc digest, 413 cho payload quá lớn, 415 cho sai kiểu nội dung, 422 cho dữ liệu sai schema và 503 cho lỗi truy xuất bằng chứng. Khi thử lại sau 503, dùng lại UUID và CSV gốc.

## Chạy trên Linux hoặc macOS

```sh
python3.13 -m venv .venv
cp .env.example .env
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Terminal thứ hai chạy `.venv/bin/python -m scripts.demo --interactive`. [Lệnh PowerShell](../README.md#chạy-trong-vài-phút) nằm ở README.

### Chạy từng tích hợp

Cài `requirements-integrations.txt` vào môi trường đang chạy dịch vụ. Cập nhật `.env` rồi khởi động lại API.

| Mục đích | Cấu hình |
| --- | --- |
| Chroma | `AMACFA_VECTOR_BACKEND=chroma`. Chỉ mục nằm trong `AMACFA_STATE_DIR/chroma`. |
| Neo4j | `AMACFA_GRAPH_BACKEND=neo4j`, `AMACFA_NEO4J_URI`, `AMACFA_NEO4J_USER`, `AMACFA_NEO4J_PASSWORD`, `AMACFA_NEO4J_DATABASE`. Driver kiểm tra kết nối khi khởi động. |
| OpenAI | `AMACFA_LLM_BACKEND=openai` và `OPENAI_API_KEY`. Mặc định `gpt-4o`. |
| Anthropic | `AMACFA_LLM_BACKEND=anthropic` và `ANTHROPIC_API_KEY`. Mặc định `claude-sonnet-4-6`. |
| Giữ checkpoint | `AMACFA_STATE_DIR` có quyền ghi, volume bền vững và một Uvicorn worker. |

Chạy toàn bộ stack bằng `docker compose up --build -d` sau khi tạo `.env`. Stack này dùng Chroma và Neo4j. Nếu cần đổi mật khẩu Neo4j ban đầu, đặt `NEO4J_DEMO_PASSWORD` trước lần tạo volume đầu tiên. `docker compose logs -f auditor` hiển thị mã hồ sơ, tên Agent, số mục và thời gian xử lý. `docker compose down` dừng dịch vụ và giữ volume.

## Kiểm thử và đánh giá

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m scripts.evaluate
```

Các lệnh dùng Python của môi trường ảo. Bộ test chạy Chroma và mock HTTP cho SDK khi đã cài dependencies tích hợp. Để chạy bài test Neo4j thật, cung cấp `AMACFA_TEST_NEO4J_URI` và `AMACFA_TEST_NEO4J_PASSWORD` cho một database thử nghiệm riêng. Chương trình đánh giá so khớp cả quy tắc, tập dòng nguồn và mã điều khoản. Hai fixture tổng hợp kiểm tra đúng các tình huống đã cài và một lô đối chứng. Chất lượng trên dữ liệu AP thực cần được đánh giá bằng tập gán nhãn riêng.

## Phạm vi triển khai

Bản portfolio chạy một tiến trình và một tenant. Hai Bearer token đại diện hai vai trò dùng chung trong môi trường demo. SHA-256 hỗ trợ kiểm tra tính nhất quán giữa dữ liệu và báo cáo. Xác thực danh tính người duyệt và bảo vệ lịch sử khỏi sửa đổi dựa vào hạ tầng lưu trữ, kiểm soát truy cập và nhật ký bất biến trong triển khai doanh nghiệp.

Trước khi xử lý hóa đơn thật, cần OIDC/SSO và phân quyền theo tenant, TLS và mạng riêng, kho bí mật, mã hóa và vòng đời xóa dữ liệu cho SQLite/Neo4j, chính sách audit log và sao lưu. Để scale sang nhiều worker, cần checkpointer dùng chung (ví dụ PostgreSQL), cơ chế khóa hoặc hàng đợi theo mã hồ sơ, và quy trình migration policy/workflow. Quy trình hiện kiểm tra hồ sơ CSV, dùng catalog giả lập và xuất báo cáo phục vụ xác minh nghiệp vụ. [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers).
