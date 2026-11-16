# Báo cáo kiểm toán công nợ phải trả

Rà soát 10 hóa đơn. Ghi nhận 5 tín hiệu, gồm 4 mức cao, liên quan đến 8 dòng CSV.

- Hồ sơ `be850d2d-1716-43b3-af4f-f8c179bb9ac0`
- Chính sách nội bộ `AP-DEMO-1.0`
- SHA-256 CSV `4d55e9af6d8f3ae7265c5c7c8d8bc95c7fcd72db8bea8842b5e70cdfe33da0eb`
- SHA-256 gói bằng chứng đã duyệt `efce3f41e53bd69655da471946f3975540d613d8ac4fc3e86acfe6cf4462a5ab`
- Phê duyệt `reviewer` · `2026-11-16T12:59:57.962549+00:00`

Các tín hiệu cần được xác minh bằng hồ sơ gốc trước khi đưa ra kết luận nghiệp vụ.

## Việc cần ưu tiên

- **F-0001** · Đối chiếu PO, hóa đơn gốc và lịch sử thanh toán của các dòng được dẫn.
- **F-0002** · Kiểm tra hồ sơ phê duyệt và xác nhận thẩm quyền theo ma trận phân quyền.
- **F-0004** · Đối chiếu nhật ký quyền truy cập và yêu cầu phê duyệt độc lập.

## Bằng chứng và căn cứ chính sách

### F-0001 · Ngăn thanh toán trùng

- Quy tắc `DUPLICATE_INVOICE` · Mức Cao · Dòng CSV **2, 3**
- Điều khoản `AP-01@AP-DEMO-1.0` · Kiểm tra số hóa đơn đã được ghi nhận theo mã nhà cung cấp trước khi thanh toán.
- Xác minh · Đối chiếu PO, hóa đơn gốc và lịch sử thanh toán của các dòng được dẫn.
- Điều khoản tham khảo · `AP-05@AP-DEMO-1.0`, `AP-04@AP-DEMO-1.0`

### F-0002 · Phê duyệt theo hạn mức

- Quy tắc `MISSING_APPROVAL` · Mức Cao · Dòng CSV **4**
- Điều khoản `AP-02@AP-DEMO-1.0` · Hóa đơn đạt hoặc vượt hạn mức theo tiền tệ phải có người phê duyệt được ghi nhận.
- Xác minh · Kiểm tra hồ sơ phê duyệt và xác nhận thẩm quyền theo ma trận phân quyền.
- Chỉ số · Giá trị `12000.00` · Hạn mức `10000` · Tiền tệ `USD`
- Điều khoản tham khảo · `AP-03@AP-DEMO-1.0`, `AP-01@AP-DEMO-1.0`

### F-0003 · Kiểm soát cộng gộp giao dịch

- Quy tắc `POTENTIAL_SPLIT` · Mức Trung bình · Dòng CSV **6, 7**
- Điều khoản `AP-04@AP-DEMO-1.0` · Rà soát các giao dịch dưới hạn mức của cùng nhà cung cấp và người đề nghị trong cửa sổ chính sách, theo từng tiền tệ.
- Xác minh · Đối chiếu hợp đồng, PO, thời điểm giao hàng và mục đích mua sắm của cả nhóm hóa đơn.
- Chỉ số · Tổng `10300.00` · Hạn mức `10000` · Tiền tệ `USD` · Cửa sổ (ngày) `7`
- Điều khoản tham khảo · `AP-01@AP-DEMO-1.0`, `AP-02@AP-DEMO-1.0`

### F-0004 · Phân tách nhiệm vụ

- Quy tắc `SELF_APPROVAL` · Mức Cao · Dòng CSV **5**
- Điều khoản `AP-03@AP-DEMO-1.0` · Người đề nghị và người phê duyệt thanh toán phải là hai người khác nhau.
- Xác minh · Đối chiếu nhật ký quyền truy cập và yêu cầu phê duyệt độc lập.
- Điều khoản tham khảo · `AP-02@AP-DEMO-1.0`, `AP-01@AP-DEMO-1.0`

### F-0005 · Xác minh tài khoản nhận tiền

- Quy tắc `SHARED_ACCOUNT` · Mức Cao · Dòng CSV **8, 9**
- Điều khoản `AP-05@AP-DEMO-1.0` · Một tài khoản nhận tiền được dùng chung bởi nhiều mã nhà cung cấp cần được xác minh độc lập.
- Xác minh · Đối chiếu hồ sơ nhà cung cấp và xác minh tài khoản qua đầu mối đã đăng ký.
- Chỉ số · Số nhà cung cấp `2` · Đường dẫn quan hệ `Vendor <- Invoice -> Account <- Invoice -> Vendor`
- Điều khoản tham khảo · `AP-01@AP-DEMO-1.0`, `AP-02@AP-DEMO-1.0`
