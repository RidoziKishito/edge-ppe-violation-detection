# 06 - Robust PPE detection under adverse conditions

## 1. Mục tiêu

Tăng độ bền của detector và tracker khi camera gặp người/PPE nhỏ, thiếu sáng, motion blur hoặc người bị cắt khỏi ảnh. Đây là nhánh bổ trợ trước ByteTrack: tracker không thể giữ ID nếu detector liên tục bỏ sót Person.

Không đưa pose estimation, super-resolution hoặc deblurring sinh chi tiết vào core.

## 2. Phương pháp theo từng vấn đề

| Vấn đề | Phương pháp ưu tiên | Cách dùng | Phạm vi |
|---|---|---|---|
| Người/PPE quá nhỏ | P2 baseline, sau đó SAHI/tiled inference | P2 được train ở Module 1. SAHI chia frame/ROI thành tile chồng lấn, detect từng tile và gộp box bằng NMS | Candidate có gate latency |
| PPE nhỏ trong person box | Two-stage person-crop | Detect Person, crop có padding, phóng về input size rồi chạy detector PPE; map box về frame gốc | Candidate thay thế SAHI khi đã detect được Person |
| Ảnh tối | Train augmentation + conditional gamma/CLAHE | Augment brightness/gamma/contrast/noise khi train; lúc chạy chỉ enhance frame dưới ngưỡng sáng | Core experiment |
| Ánh sáng không đều nghiêm trọng | Zero-DCE | Dùng làm research baseline nếu gamma/CLAHE chưa đủ; phải đo artifact và latency | Conditional |
| Motion blur | Motion-blur augmentation + blur gate | Train với kernel blur nhiều hướng/độ dài; variance of Laplacian chỉ báo frame quá mờ để hạ độ chắc chắn | Core experiment |
| Người bị cắt khỏi ảnh | Random-crop training | Tạo mẫu truncated nhưng giữ box phần còn nhìn thấy; đánh giá riêng theo mức truncation | Core experiment |
| Đầu/tay/chân ngoài ảnh | Visibility gate | Kiểm tra person/PPE box với biên ảnh và vùng tỷ lệ cơ thể; không nhìn thấy thì trả `UNKNOWN` | Core runtime rule |

Không mặc định chạy đồng thời P2, BiFPN, SAHI và person-crop. Dùng error analysis và ablation để chọn cấu hình nhỏ nhất đạt mục tiêu accuracy-latency.

## 3. Luồng xử lý

```text
Frame
  -> đo brightness và blur
  -> tăng sáng có điều kiện nếu cần
  -> standard detector hoặc SAHI theo camera/ROI cấu hình
  -> nếu Person đã thấy nhưng PPE quá nhỏ: person-crop candidate
  -> merge NMS về tọa độ frame gốc
  -> ByteTrack cho Person
  -> gán PPE bằng tâm box trong person box
  -> visibility gate
  -> WORN / NOT_WORN / UNKNOWN
  -> temporal event theo track_id
```

SAHI nên bật cho far-field ROI hoặc camera có nhiều small boxes; không chạy mọi tile trên mọi frame nếu không đạt ngân sách edge. Person-crop không cứu được Person đã bị bỏ sót, nên nó bổ sung chứ không thay SAHI/P2 trong trường hợp người quá nhỏ.

## 4. Quy tắc visibility

- Head region ngoài cạnh trên hoặc không đủ pixel: helmet/goggles là `UNKNOWN` nếu không có detection khẳng định đáng tin cậy.
- Hand region bị che/quá nhỏ: gloves là `UNKNOWN`.
- Foot region ngoài cạnh dưới: boots là `UNKNOWN`.
- Frame quá mờ hoặc quá tối làm confidence dưới ngưỡng tin cậy: không mở vi phạm mới.
- `UNKNOWN` có thể giữ event cũ trong một khoảng ngắn nhưng không được đổi thành `NOT_WORN`.

Pose không cần thiết cho gate này. Có thể ước lượng vùng đầu, thân, tay và chân theo tỷ lệ person box cùng quan hệ với biên ảnh.

## 5. Dữ liệu và huấn luyện

### Train

- Dùng ảnh có box hiện tại/Dataset v2.
- Thêm gamma, brightness, contrast, sensor noise, motion blur và random crop theo xác suất có kiểm soát.
- Không biến mọi ảnh thành ảnh xấu; luôn giữ tỷ lệ clean đủ lớn.
- Nếu fine-tune với tile/person-crop, giữ manifest để biết sample đến từ full frame hay crop.

### Validation/test

- Giữ clean set bất biến.
- Tạo `robustness_v1` từ bản sao có cùng nhãn với nhiều severity cho low-light và blur.
- Có field subset thật cho small/far, low-light, motion blur và truncation.
- Không dùng ảnh enhanced, ảnh sinh hoặc corrupted final test để tune rồi báo lại trên chính tập đó.

## 6. Thí nghiệm tối thiểu

| ID | Cấu hình | Mục đích |
|---|---|---|
| R0 | Detector cuối trên clean/robustness_v1 | Baseline |
| R1 | R0 + P2 hoặc architecture đã chọn | Đo gain small-object ở cấp model |
| R2 | R1 + SAHI | Đo AP_small/recall so với latency |
| R3 | R1 + person-crop | So với SAHI; không chạy cả hai mặc định |
| R4 | Model đã chọn + low-light/motion-blur augmentation | Đo relative degradation |
| R5 | R4 + conditional gamma/CLAHE | Kiểm tra preprocessing có giúp hay tạo false positive |
| R6 | R4/R5 + visibility gate + ByteTrack | Đo false violation, HOTA/IDF1 và event stability |

Metric chính: `AP_small`, recall theo PPE, false-negative rate, relative degradation theo severity, HOTA/IDF1, false violations do vùng ngoài ảnh, FPS và P95 latency.

## 7. Quyết định phạm vi

**Core:** architecture small-object đã chọn, low-light/motion-blur augmentation, visibility gate và ByteTrack.

**Chỉ giữ một candidate runtime:** SAHI hoặc person-crop dựa trên kết quả AP_small/latency.

**Conditional:** Zero-DCE khi gamma/CLAHE không đủ.

**Không làm trong core:** pose training, deblurring, super-resolution và sinh toàn bộ test set bằng AI.

## 8. Nguồn chính

- SAHI: https://arxiv.org/abs/2202.06934
- Zero-DCE: https://openaccess.thecvf.com/content_CVPR_2020/html/Guo_Zero-Reference_Deep_Curve_Estimation_for_Low-Light_Image_Enhancement_CVPR_2020_paper.html
- Motion blur in online object detection: https://openaccess.thecvf.com/content/CVPR2021/html/Sayed_Improved_Handling_of_Motion_Blur_in_Online_Object_Detection_CVPR_2021_paper.html
- ByteTrack: https://github.com/FoundationVision/ByteTrack
