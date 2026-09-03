# AHS v1: cách chạy và ý nghĩa của từng thành phần

## 1. AHS v1 hiện làm gì?

AHS v1 là một portfolio SAT có ngân sách chung. Trên mỗi graph, controller:

1. đọc các đặc trưng đơn giản của graph;
2. chọn một thứ tự backend cố định;
3. cấp cho mỗi backend một phần của tổng thời gian;
4. dừng ngay khi tìm được chu trình Hamilton hợp lệ;
5. kiểm tra lại tour bằng một verifier độc lập trước khi báo `SATISFIABLE`.

Đây chưa phải mô hình học máy. Các luật chọn route và tỷ lệ thời gian nằm trong
[`benchmarks/ahs_policy.json`](../benchmarks/ahs_policy.json), nên mỗi lần chạy có
thể tái lập và kiểm tra được. Việc tích hợp hiện ở mức tiến trình; các backend
chưa truyền SAT state hoặc learned clause cho nhau.

## 2. Vì sao AHS v0 không được dùng tiếp?

Lần chạy `ahs-open33-1800s` cho kết quả `UNKNOWN` trên cả 33 instance. Log còn
cho thấy model đầu tiên của backend CEGAR cũ thường chứa nhiều cycle rất ngắn và
số subtour gần như không tiến triển.

Rà soát source tìm được lỗi quan trọng hơn: wrapper `Solver_CARadd` đã chuyển
luồng lệnh cardinality riêng của Cardinality-CDCL thẳng sang hàm thêm mệnh đề CNF
thông thường của CaDiCaL. Hai giao thức này không tương đương. Vì vậy cấu hình đó
không mã hóa đúng ràng buộc exactly-one và không được xem là một replay hợp lệ của
kết quả bài báo.

AHS v1 xử lý vấn đề này theo hai lớp:

- policy mặc định không còn gọi backend replay lỗi;
- source FFI được đổi sang mã hóa exactly-one Sinz bằng CNF chuẩn. Backend FFI
  này vẫn chưa được đưa trở lại portfolio cho đến khi được biên dịch và benchmark
  độc lập trên môi trường Linux.

Kết quả 33/33 `UNKNOWN` cũ chỉ có giá trị chẩn đoán. Không dùng nó để kết luận
phương pháp trong bài báo yếu hay mạnh.

Log cũ vẫn cho hai tín hiệu hữu ích về HCup. Trong 33 lượt HFP, 23 lượt chưa tạo
được model hoàn chỉnh; 10 lượt đã tạo ít nhất một model nhưng chưa tìm được tour.
Riêng `graph761` tạo 1.420 model và báo 2.892 blocking clause trước timeout. Điều
này cho thấy HFP có hoạt động nhưng không hội tụ trong phần ngân sách 10--30% đã
được cấp. Lần chạy cũ cũng chưa thử HCup outside. Vì vậy `residual_v1` đưa outside
lên trước và cấp toàn bộ core-33 cho hai HCup mode bổ sung; đây là thay đổi cần
đo, không phải tuyên bố rằng tỷ lệ mới đã tối ưu.

## 3. Các backend đang chạy

| Backend | Vai trò | Điều kiện chấp nhận |
|---|---|---|
| `cegar_sinz_2loop_2opt3` | CEGAR CNF chuẩn, exact-one Sinz, vá cycle bằng 2-opt | Tour qua verifier độc lập |
| `hcup_outside_mergecutset` | CEGAR của HCup với merge-cutset | Tour qua verifier độc lập |
| `hcup_hfp_preventsubcycle` | IPASIR-UP ngăn subtour ngay khi SAT đang tìm kiếm | Tour qua verifier độc lập |

Các backend dùng cùng giới hạn một luồng qua biến môi trường do controller đặt.
Build time không tính vào ngân sách giải.

## 4. Hai policy cần phân biệt

### `rule_v2`: policy tổng quát

Đây là mặc định khi giải một instance chưa biết. Route chỉ phụ thuộc vào mật độ
`m/n` và tỷ lệ đỉnh bậc 2.

| Nhóm graph | Thứ tự và tỷ lệ ngân sách |
|---|---|
| dense | HCup outside 50%, CEGAR Sinz 35%, HCup HFP 15% |
| sparse, nhiều đỉnh bậc 2 | CEGAR Sinz 40%, HCup outside 30%, HCup HFP 30% |
| sparse khác | CEGAR Sinz 45%, HCup outside 35%, HCup HFP 20% |

Các tỷ lệ này là giả thuyết kỹ thuật ban đầu, chưa phải kết luận thực nghiệm.
Muốn công bố chúng cần ablation cùng máy, cùng timeout và nhiều seed/order khi
backend có yếu tố không tất định.

### `residual_v1`: policy cho tập đã biết CEGAR không giải được

Core 33 được tạo từ những instance mà CEGAR trước đó đã bỏ sót. Chạy lại CEGAR
trên chính tập dư này chỉ lặp lại chi phí đã biết. `residual_v1` vì thế chỉ chạy:

- HCup outside: 60--65% ngân sách;
- HCup HFP: 35--40% ngân sách.

Policy này dùng để tìm coverage bổ sung trên core 33. Không được báo cáo nó như
policy tổng quát cho toàn bộ FHCP.

## 5. Cài đặt và kiểm tra bắt buộc

Từ thư mục gốc repository:

```bash
./setup_dependencies.sh
./setup_dependencies.sh --check
```

Lệnh `--check` không chỉ kiểm tra file tồn tại. Nó chạy cả ba backend mặc định
trên `graph1.col`, đọc tour và xác minh từng cạnh. Nếu smoke test này thất bại thì
không nên chạy benchmark dài.

## 6. Lệnh chạy

Giải một graph chưa biết bằng policy tổng quát:

```bash
./run_ahs.sh \
  --input FHCPCS-col/graph950.col \
  --policy rule_v2 \
  --timeout 1800 \
  --no-build
```

Xem route mà không chạy solver:

```bash
./run_ahs.sh \
  --input FHCPCS-col/graph950.col \
  --policy rule_v2 \
  --timeout 1800 \
  --dry-run
```

Chạy core 33 với policy residual:

```bash
./run_ahs_benchmark.sh \
  --timeout 1800 \
  --output benchmark-runs/ahs-residual33-v1-1800s
```

Với 33 instance chạy tuần tự, cap 1.800 giây có trần khoảng 16,5 giờ; cap 3.600
giây có trần khoảng 33 giờ, chưa tính thời gian setup. Instance giải sớm sẽ làm
tổng thời gian ngắn hơn.

Để đóng terminal và quay lại xem sau:

```bash
nohup ./run_ahs_benchmark.sh \
  --timeout 1800 \
  --output benchmark-runs/ahs-residual33-v1-1800s \
  --resume \
  > ahs-residual33-v1-1800s.console.log 2>&1 &
```

Nếu máy bị ngắt, chạy lại đúng lệnh có `--resume`; runner chỉ bỏ qua record đã
hoàn tất trong `results.jsonl`.

Không dùng `--resume` với thư mục `ahs-open33-1800s` cũ: manifest của lần chạy
đó thuộc policy/backend lỗi. Hãy dùng một thư mục output mới như ví dụ trên.

## 7. Cách đọc kết quả

Mỗi lần chạy đơn tạo một thư mục trong `ahs-runs/`, gồm:

- `manifest.json`: graph, hash source/binary/config, policy và môi trường;
- `summary.json`: trạng thái cuối, backend thắng, thời gian và từng stage;
- `raw/`: stdout/stderr nguyên gốc của từng backend;
- `solution.tour`: chỉ xuất hiện khi tour đã được xác minh.

Ba trường cần đọc cùng nhau:

- `status`: `SATISFIABLE`, `UNSATISFIABLE`, `UNKNOWN` hoặc `ERROR`;
- `route_exhausted`: mọi stage đã kết thúc mà chưa có kết luận;
- `budget_exhausted`: stage cuối chạm deadline tổng. Cả hai trường này đều không
  có nghĩa graph vô nghiệm.

Với benchmark nhiều instance, `results.jsonl` chứa một record cho từng cặp
instance--variant. Mỗi kết quả SAT vẫn có `verified=true`; nếu không, runner đổi
trạng thái thành `INVALID_SAT`.

## 8. Phần chưa được tích hợp

AHS v1 chưa chuyển learned clause hay cut giữa các backend. SAT repair, CRE--CEGAR
và wrapper Cardinality-CDCL lịch sử cũng chưa thuộc policy mặc định. Chúng chỉ nên
được thêm sau khi có:

1. kiểm thử đúng/sai trên tập nhỏ có đáp án độc lập;
2. timeout cứng và kiểm soát một luồng;
3. ablation cho thấy có unique win hoặc giảm thời gian có ý nghĩa;
4. log đủ để chỉ ra cơ chế nào tạo ra lợi ích.

Do đó bước benchmark tiếp theo có mục tiêu cụ thể: đo xem HCup outside và HFP có
giải thêm instance nào trong core 33. Nếu vẫn không có coverage mới, dữ liệu
activity trong `stage_results[].backend_activity` được dùng để phân biệt solver
đang tiến triển chậm, lặp model/subtour, hay gần như không backtrack. Khi đó mới
chọn đúng chỗ để tối ưu tiếp thay vì chỉ tăng timeout.
