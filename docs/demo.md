# Kịch bản video portfolio · 3 phút

**Chuẩn bị**. Khởi động API theo README. Mở terminal, `data/invoices_mixed.csv` và một trình Markdown preview. Bộ dữ liệu chỉ chứa thông tin tổng hợp. Chạy lệnh từ môi trường ảo.

```sh
python -m scripts.demo --interactive
```

| Thời lượng | Trên màn hình | Lời thoại gợi ý |
| --- | --- | --- |
| 00:00–00:20 | Mở CSV, trỏ vào dòng 6–7 và 8–9 | “Đây là một lô hóa đơn công nợ phải trả. Một giao dịch có thể hợp lệ khi xem riêng nhưng đáng kiểm tra khi đối chiếu với các dòng khác hoặc với hồ sơ nhà cung cấp.” |
| 00:20–00:55 | Chạy demo đến dấu nhắc của reviewer | “AMACFA ghi nhận năm tín hiệu. Nhóm chia nhỏ gồm hai hóa đơn tổng 10.300 USD trong cửa sổ chính sách. Hai mã nhà cung cấp khác nhau cũng dùng chung một token tài khoản.” |
| 00:55–01:25 | Cho thấy `awaiting_review`, SHA-256 và HTTP 409. Đối chiếu dòng CSV với `AP-05` | “Mỗi tín hiệu có dòng nguồn và điều khoản. Analyst gửi hồ sơ. Reviewer kiểm tra đúng gói bằng chứng có hash này trước khi báo cáo được xuất.” |
| 01:25–01:55 | Nhập `approve` và mở tệp Markdown vừa sinh | “LangGraph tiếp tục từ checkpoint và ra báo cáo với việc cần ưu tiên và bước xác minh cho từng phát hiện. Demo đã đối chiếu SHA-256 của tệp tải xuống.” |
| 01:55–02:25 | Hiện sơ đồ README và trỏ tới Forensic, Compliance, Reporting | “Cypher truy hồi quan hệ theo phạm vi hồ sơ. Ánh xạ có phiên bản chọn điều khoản áp dụng. Khi bật LLM, model chỉ nhận mã phát hiện và mã kiểm soát để đề xuất thứ tự xử lý.” |
| 02:25–03:00 | Chạy `python -m scripts.evaluate`, mở kết quả đối chứng | “Bài kiểm tra so cả quy tắc, tập dòng và mã kiểm soát. Bộ tổng hợp ghi nhận đúng 5 phát hiện, và lô đối chứng có 0 phát hiện.” |

Nếu quay ở chế độ offline, có thể cho thấy trường `ranking_source` trong JSON. Nếu dùng LLM, kiểm tra trường này để biết nhà cung cấp đã trả kết quả hay ứng dụng đã dùng `fallback`. Có thể quay nhánh `return` bằng `python -m scripts.demo --decision return` và cho thấy báo cáo tiếp tục bị chặn.

## Dòng mô tả cho CV

> Xây dựng hệ thống kiểm toán AP nhiều Agent với LangGraph, FastAPI, Chroma và Neo4j, truy vết phát hiện đến dòng dữ liệu và điều khoản, rồi xuất báo cáo qua cổng duyệt gắn SHA-256. Kiểm chứng năm tình huống rủi ro trên dữ liệu tổng hợp và khôi phục hồ sơ qua checkpoint SQLite.
