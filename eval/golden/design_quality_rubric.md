# Rubric chấm chất lượng thiết kế do Modeler đề xuất (v0.1-draft)

**Trạng thái:** `DRAFT`. Trọng số, ngưỡng đạt và quy tắc hard failure là **đề xuất (Proposed)**, chờ nhóm thống nhất trước khi dùng để ra quyết định.
**Phạm vi:** chấm chất lượng **thiết kế dữ liệu** (grain, khóa, quan hệ, metric, làm sạch, dashboard, xử lý mơ hồ). Không chấm văn phong hay độ dài của đầu ra LLM.
**Đối tượng:** Ánh và Tuấn Anh dùng để chấm độc lập. Tuấn chịu trách nhiệm bộ đáp án tham chiếu, không phải đáp án duy nhất.
**Phụ thuộc chưa đáp ứng:** cấu trúc `DataDesign` thực tế (`app/agents/schemas.py`) chưa được đối chiếu. Mọi trường được nêu dưới đây là trường nghiệp vụ, phải ánh xạ sang schema trước khi chấm tự động. Xem mục 9.

---

## 1. Nguyên tắc

1. **Chấm bằng bằng chứng.** Mỗi điểm phải kèm trích dẫn từ đầu ra Modeler hoặc từ dữ liệu. Không có bằng chứng thì không cho điểm cao.
2. **Chấp nhận nhiều thiết kế hợp lệ.** Chấm theo tính tương đương nghiệp vụ, không so khớp từng tên bảng hay cột.
3. **Không để tổng điểm che lỗi nghiêm trọng.** Hard failure được xét trước, rồi mới đến điểm.
4. **Quan sát không phải luật.** Thiết kế coi một quan sát thống kê là ràng buộc bắt buộc (ví dụ "khóa phải duy nhất" dựa trên lô hiện có) bị coi là lỗi, theo FR-08.
5. **Hỏi lại là một phần của chất lượng.** Hỏi đúng lúc được điểm; hỏi thừa, hoặc tự quyết điểm mơ hồ trọng yếu, bị trừ điểm.

## 2. Thang điểm cho từng tiêu chí

| Điểm | Nghĩa |
|---|---|
| 0 | Sai hoặc thiếu nghiêm trọng: không có nội dung cần thiết, hoặc có mâu thuẫn làm thiết kế không dùng được |
| 1 | Yếu: có đề cập nhưng sai đáng kể, thiếu căn cứ, chưa đủ để triển khai |
| 2 | Đạt một phần: có cơ sở nhưng thiếu chi tiết, cần sửa trước khi dùng |
| 3 | Tốt: đúng, có căn cứ, nhất quán, dùng được |
| 4 | Rất tốt: đúng, đầy đủ, nhất quán, có bằng chứng và xử lý rõ các trường hợp biên |

## 3. Tiêu chí và trọng số (Proposed)

| Mã | Tiêu chí | Trọng số | Lý do trọng số |
|---|---|---|---|
| A | Grain | 20% | Grain sai làm mọi khóa, quan hệ và metric sai theo |
| B | Keys | 15% | Khóa sai làm đếm trùng hoặc mất bản ghi |
| C | Relationships | 15% | Quan hệ sai (1-N thành 1-1 hoặc N-N) làm nhân dòng |
| D | Metrics | 15% | Là đầu ra nghiệp vụ trực tiếp |
| E | Cleaning rules | 10% | Có thể làm mất dữ liệu hoặc đổi ý nghĩa |
| F | Dashboard | 10% | Phải khả thi trên các bảng đã đề xuất |
| G | Xử lý mơ hồ (FR-05) | 15% | Là mục tiêu chính của FR-05 |

Tổng: 100%. Grain, keys và relationships cộng lại 50%, phản ánh ưu tiên của đặc tả về tính đúng của cấu trúc.

## 4. Công thức tính điểm

Với điểm gốc `s_i` ∈ {0,…,4} cho tiêu chí `i` và trọng số `w_i`:

```
điểm thang 100 = 100 × Σ (w_i × s_i / 4)
```

Ví dụ: Grain 3, Keys 4, Relationships 2, Metrics 3, Cleaning 3, Dashboard 2, Mơ hồ 1:
`100 × (0,20×3/4 + 0,15×4/4 + 0,15×2/4 + 0,15×3/4 + 0,10×3/4 + 0,10×2/4 + 0,15×1/4)` = 100 × (0,15 + 0,15 + 0,075 + 0,1125 + 0,075 + 0,05 + 0,0375) = 100 × 0,65 = **65,0**.

Quy tắc bắt buộc: nếu có hard failure, kết quả là **Không đạt**, bất kể điểm thang 100.

## 5. Hard failure (Proposed)

Mỗi mục dưới đây làm thiết kế không đạt. Số hiệu là mã dùng trong phiếu chấm.

| Mã | Điều kiện | Ví dụ |
|---|---|---|
| HF-1 | Thiếu grain cho một bảng fact, hoặc grain không thể kiểm tra | "Thông tin khách hàng" cho một bảng fact |
| HF-2 | Khóa được đề xuất không duy nhất trên dữ liệu, mà không có lý do chấp nhận | Đề xuất `studentVle(code_module, code_presentation, id_student, id_site, date)` làm khóa chính, trong khi khóa chỉ duy nhất 79,39% |
| HF-3 | Khóa được chọn chỉ vì tên cột có hậu tố `_id` mà không có bằng chứng | Chọn `customer_id` làm khóa khách thật khi `customer_unique_id` mới là định danh khách |
| HF-4 | Quan hệ được suy ra chỉ từ tên cột giống nhau, không có bằng chứng về giá trị | Nối `order_reviews.review_id` với `orders.order_id` |
| HF-5 | Metric đếm trùng do grain sai (ví dụ cộng doanh thu ở mức dòng hàng rồi nhân với số đơn) | Tổng doanh thu cộng `order_payments` vào `order_items` |
| HF-6 | Cleaning rule xóa hoặc đổi dữ liệu mà không có bằng chứng và không có câu hỏi | Xóa 8 đơn `delivered` thiếu ngày giao mà không hỏi |
| HF-7 | Tự quyết một điểm mơ hồ trọng yếu mà không hỏi, và không nêu giả định | Chọn `payment_value` là tổng đã gồm lãi trả góp mà không hỏi |
| HF-8 | Đầu ra cả `design` và `questions` cùng lúc, hoặc không có cả hai | Vi phạm định nghĩa của `ModelerOutput` (theo bản đồ codebase) |
| HF-9 | Bịa dữ liệu, bảng, cột hoặc quan hệ không có trong nguồn | Có bảng `dim_date` với ngày lịch khi dữ liệu chỉ có số ngày tương đối |

## 6. Quy tắc chấp nhận thiết kế thay thế

Thiết kế khác với bản tham chiếu vẫn được chấp nhận nếu thỏa **tất cả** các điều kiện:

1. Đáp ứng cùng yêu cầu nghiệp vụ.
2. Grain được định nghĩa rõ và nhất quán với khóa.
3. Khóa xác định đúng bản ghi theo grain.
4. Quan hệ đúng với bằng chứng và có cardinality đúng.
5. Metric không đếm trùng và dùng đúng grain.
6. Không vi phạm hard failure.
7. Mọi khác biệt so với tham chiếu được giải thích.

Phân loại kết quả so sánh với tham chiếu:

| Loại | Ý nghĩa | Xử lý |
|---|---|---|
| Hard failure | Sai nghiêm trọng, không chấp nhận | Trả lại Modeler |
| Major issue | Ảnh hưởng đáng kể đến kết quả, cần sửa | Trừ điểm, yêu cầu sửa |
| Minor issue | Thiếu sót nhỏ, không đổi ý nghĩa | Ghi nhận |
| Acceptable alternative | Khác biệt nhưng hợp lệ | Không trừ điểm, ghi lý do |

## 7. Tiêu chí G — xử lý mơ hồ (chi tiết)

Tiêu chí này dùng bộ tình huống trong `ambiguity_cases.csv` (22 tình huống, cột `must_ask`).

| Điểm | Tiêu chí |
|---|---|
| 4 | Hỏi đúng mọi tình huống `must_ask = Yes`, không hỏi thừa tình huống `No`, nêu giả định đúng cho tình huống `Recommended` |
| 3 | Hỏi đúng hầu hết tình huống bắt buộc (ít hơn 1 bỏ sót), không hỏi thừa đáng kể |
| 2 | Bỏ sót một tình huống bắt buộc quan trọng hoặc hỏi thừa nhiều lần |
| 1 | Bỏ sót nhiều tình huống bắt buộc, hoặc tự chọn cách hiểu mà không nêu giả định |
| 0 | Không nhận ra mơ hồ nào và không hỏi gì |

Đây là chỗ hỏi thừa được trừ điểm: hỏi về tình huống `No` (ví dụ kiểu `date_*` đã có mô tả chính thức) làm giảm điểm.

## 8. Ví dụ

**Thiết kế đạt (mô tả ngắn):** `fact_order_item` với grain "một dòng hàng trong một đơn", khóa (`order_id`, `order_item_id`) duy nhất 100%, quan hệ 1-N tới `orders` và `products`, metric doanh thu có công thức và điều kiện lọc `order_status`, hỏi lại về `payment_value` (OLI-01). Điểm dự kiến: 80–90 (Proposed).

**Thiết kế sai (mô tả ngắn):** `fact_vle_daily` với khóa (code_module, code_presentation, id_student, id_site, date) được đề xuất là khóa chính, không hỏi về dòng trùng, metric tổng click cộng trực tiếp. Hard failure HF-2 và HF-7. Kết quả: **Không đạt**.

**Thiết kế thay thế hợp lệ:** cùng `fact_vle_daily` nhưng khóa thay thế số nguyên, grain ghi là "một bản ghi nguồn", kèm câu hỏi về cộng dồn và giả định rõ ràng. Thuộc "Acceptable alternative", không trừ điểm.

*Ví dụ trên là minh họa, chưa dùng làm đáp án chuẩn cho bất kỳ dataset nào.*

## 9. Phiếu chấm (mẫu)

| Trường | Nội dung |
|---|---|
| Run ID | |
| Dataset và phiên bản | |
| Input (yêu cầu, hồ sơ, câu hỏi, câu trả lời) | |
| Design version | |
| Điểm gốc A–G (0–4) và bằng chứng từng điểm | |
| Trọng số áp dụng | Theo mục 3 (phiên bản rubric: v0.1-draft) |
| Điểm thang 100 | |
| Hard failure (mã HF-x nếu có) | |
| Kết quả | Đạt / Không đạt / Đạt có điều kiện |
| Acceptable alternative (nếu có) | |
| Lỗi nghiêm trọng / lớn / nhỏ | |
| Câu hỏi nên hỏi nhưng chưa hỏi | |
| Câu hỏi không cần thiết đã hỏi | |
| Quan sát thực tế và giả thuyết nguyên nhân (ghi rõ là giả thuyết) | |
| Đề xuất cho người phụ trách Modeler | |
| Người chấm và ngày | |

## 10. Xử lý bất đồng giữa hai người chấm

1. Hai người chấm độc lập trước, không trao đổi.
2. Chênh lệch điểm từ 1 trở xuống trên một tiêu chí: lấy trung bình và ghi cả hai.
3. Chênh lệch từ 2 trở lên, hoặc khác nhau về hard failure: thảo luận, ghi lý do, đưa vào mục "chưa quy định rõ" để cập nhật rubric.
4. Bất đồng về việc một khác biệt có phải acceptable alternative: cần người thứ ba quyết định, ghi thành tiền lệ.
5. Mọi thay đổi rubric đi kèm tăng số phiên bản.

## 11. Gói bàn giao cho Ánh và Tuấn Anh

| Thành phần | Trạng thái |
|---|---|
| Rubric phiên bản hiện tại (file này) | Có (v0.1-draft) |
| Bộ tình huống mơ hồ (`ambiguity_cases.csv`) | Có (22 tình huống, một số gold answer chờ xác nhận) |
| Ví dụ đạt, sai, thay thế | Có (minh họa) |
| Mẫu phiếu chấm | Có (mục 9) |
| Định dạng đầu vào/đầu ra chuẩn theo `DataDesign` | **Chưa có** (cần schema thực tế, xem mục 12) |
| Đầu ra Modeler để thử | **Chưa có** |

## 12. Những điều chưa xác minh được

- **Schema `DataDesign` thực tế chưa được đọc.** Bản đồ codebase chỉ mô tả các trường nghiệp vụ. Cần `app/agents/schemas.py` để ánh xạ tiêu chí sang trường thật.
- Trọng số, ngưỡng và hard failure là đề xuất, chưa được nhóm thống nhất.
- Gold answer của các tình huống TPC-H về công thức doanh thu và quan hệ `o_totalprice` chưa được đối chiếu với đặc tả TPC-H.
- Chưa có đầu ra Modeler nào để kiểm thử rubric. Rubric chưa được thử trên dữ liệu thật.
