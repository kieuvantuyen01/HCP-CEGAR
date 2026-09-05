# AHS v1 và nhánh population-guided: cách chạy và ý nghĩa

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

Nhánh nghiên cứu kế tiếp đã có một treatment chạy được trong chính
`cegar-fix`: `cegar_sinz_population_guided`. Nó giữ một population nhỏ gồm các
cycle cover SAT đã gặp, rồi thử ghép cover hiện tại với cạnh của cover cũ. Nhánh
này là ablation riêng; `rule_v2` và các baseline cũ không tự động bật nó.

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
| `cegar_sinz_population_guided` | Sinz-CEGAR và edge-assembly recombination từ các cycle cover SAT trước | Cover trung gian được kiểm tra trong graph; tour cuối qua verifier độc lập |

## 3.1 Population-guided CEGAR làm gì?

Mỗi model SAT thỏa các ràng buộc bậc cho ta một hoặc nhiều vòng rời nhau. Module
`population_patcher.rs` lưu tối đa 13 cover khác nhau về tập cạnh. Với cover mới,
module chọn tối đa bốn cover cũ có nhiều cạnh nối chéo giữa các vòng hiện tại và
có độ đa dạng cạnh cao. Nó chỉ thử hai phép an toàn:

1. 2-opt dùng hai cạnh thay thế cùng xuất hiện trong cover cha;
2. chained k-opt trên graph hợp của cạnh cover hiện tại và cover cha.

Ứng viên chỉ được nhận nếu số vòng giảm, chứa mỗi đỉnh đúng một lần và mọi cạnh
đều có trong graph. Với degree-2 contraction, cạnh cưỡng bức không được phép bị
cắt. Nếu không tạo được ứng viên tốt hơn, CEGAR tiếp tục như cũ.

Recombination dùng deadline chung của solver. Mỗi parent có tối đa 32 vòng luân
phiên, mỗi lần guided matching tối đa 64 vòng và chained LK tối đa 32 vòng. Nếu
hết deadline, backend trả `UNKNOWN`; nếu chỉ chạm giới hạn vòng, CEGAR tiếp tục
với cover tốt nhất đã được kiểm tra. Telemetry ghi thêm `budget_exhausted`, số
vòng của từng phase và `round_limit_hits`.

Khi các lần thử liên tiếp không giảm được số vòng, patcher dùng backoff tăng dần:
bỏ qua 1, 3, 7, 15, 31 rồi tối đa 63 model trước lần thử tiếp theo. Cover mới vẫn
được lưu trong thời gian chờ. Một lần cải thiện sẽ đặt backoff về 0. Trường
`cooldown_skipped` cho biết một call chỉ quan sát cover mà không chạy local search.

AHS đặt deadline nội bộ sớm hơn thời điểm kill tiến trình con từ 20% ở cap rất
ngắn đến tối đa một giây ở cap dài. Khoảng này dành cho backend trả `UNKNOWN`,
in telemetry và đóng file; nó được áp dụng giống nhau cho hai nhánh A/B.

Các component của cover đã kiểm tra có thể sinh cut-set hợp lệ: trong mọi chu
trình Hamilton, một tập đỉnh khác rỗng và khác toàn bộ graph phải có cạnh đi vào
và đi ra. Vì vậy cut từ offspring không phụ thuộc vào việc offspring có phải
model SAT hiện tại hay không. Heuristic không bao giờ được dùng để kết luận
`UNSAT`; kết luận `SAT` vẫn phải qua verifier trên graph gốc.

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

### `residual_v1`: policy cho tập dư lịch sử

Core 33 nằm ngoài union 968 của 21 cấu hình lịch sử có dữ liệu per-instance,
trong đó có các cấu hình CEGAR đã ghi nhận. Điều này không tự chứng minh binary
`cegar-fix` hiện tại sẽ timeout trên cùng máy và cùng cap. `residual_v1` chỉ trả
lời câu hỏi hẹp hơn: hai HCup mode có bổ sung coverage ngoài mốc lịch sử đó hay
không. Policy này chạy:

- HCup outside: 60--65% ngân sách;
- HCup HFP: 35--40% ngân sách.

Không được báo cáo `residual_v1` như policy tổng quát cho toàn bộ FHCP. Nếu đánh
giá AHS v1 như một phương pháp mới, vẫn phải chạy `cegar_only` và các HCup
baseline độc lập dưới cùng điều kiện.

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

Chạy benchmark AHS tổng quát trên một tập được chọn:

```bash
./run_ahs_benchmark.sh \
  --set regression_core \
  --variants ahs_rule_v2 \
  --timeout 1800 \
  --output benchmark-runs/ahs-rule-v2-regression
```

Chạy core 33 với wrapper residual cố định:

```bash
./run_ahs_residual33.sh \
  --timeout 1800 \
  --output benchmark-runs/ahs-residual33-v1-1800s
```

Chạy A/B đúng một thay đổi trên core-33: baseline CEGAR và treatment population
được cấp cùng timeout, cùng encoding và cùng cut method:

```bash
./run_ahs_population_ablation.sh \
  --timeout 1800 \
  --output benchmark-runs/population-cegar-ablation-open33 \
  --resume
```

Nếu chỉ cần chạy treatment rồi quay lại sau, dùng wrapper cố định và `--resume`:

```bash
nohup ./run_ahs_population33.sh \
  --timeout 1800 \
  --output benchmark-runs/population-cegar-open33-1800s \
  --resume \
  > population-cegar-open33-1800s.console.log 2>&1 &
```

Policy `residual_memetic_v1` cũng đã được khai báo để thử coverage theo thứ tự
population-CEGAR, HCup outside, HFP. Không dùng policy này để đo đóng góp riêng
của recombination; cho ablation phải dùng cặp `ahs_cegar_only` và
`ahs_population_cegar_only` ở trên.

Với 33 instance chạy tuần tự, cap 1.800 giây có trần khoảng 16,5 giờ; cap 3.600
giây có trần khoảng 33 giờ, chưa tính thời gian setup. Instance giải sớm sẽ làm
tổng thời gian ngắn hơn.

Để đóng terminal và quay lại xem sau:

```bash
nohup ./run_ahs_residual33.sh \
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

Treatment mới ghi thêm phase `population_recombine`. Hai trường quan trọng là
`cycle_reduction_total` trong `phase_stats` và `population_stats` với tổng số
parent đã thử, số lần cải thiện và kích thước population. Raw log vẫn giữ từng
dòng `c population ... parents_tried=... improvements=...`. Giảm nhiều cycle chỉ là
dấu hiệu cơ chế có hoạt động; tiêu chuẩn thành công vẫn là thêm instance được
giải hoặc giảm runtime/PAR-2 trên A/B cùng điều kiện.

Với benchmark nhiều instance, `results.jsonl` chứa một record cho từng cặp
instance--variant. Mỗi kết quả SAT vẫn có `verified=true`; nếu không, runner đổi
trạng thái thành `INVALID_SAT`. Với một variant AHS, telemetry của từng solver
nằm trong `portfolio_stage_results`. Các trường top-level `increments`,
`blocking_clauses` và `backend_activity` chỉ mô tả output trực tiếp của variant;
chúng có thể là `null` khi variant đó là controller AHS.

`stage_schema_version=2` bổ sung `internal_timeout_sec` và
`termination_reason`; analyzer vẫn đọc được record schema cũ vì các trường mới
đều có giá trị mặc định khi thiếu.

Không cộng `population_stats` ở top-level cho AHS. Dùng trình phân tích paired;
trình này tự đọc `portfolio_stage_results[]`, tính coverage, timeout, PAR-2,
overhead và tạo CSV theo từng instance:

```bash
python3 tools/analyze_population_ablation.py \
  benchmark-runs/population-cegar-ablation-open33/results.jsonl
```

Manifest lưu hash của binary/config và commit/dirty state để nhận diện run. Nếu
source đang dirty, các trường này chưa đủ để rebuild chính xác vì manifest không
lưu patch. Kết quả dùng để công bố nên được tạo từ commit sạch và toolchain đã
ghi trong outer benchmark manifest.

## 8. Phần chưa được tích hợp

AHS v1 chưa chuyển learned clause hay cut giữa các backend. Population-guided
recombination hiện chỉ chia sẻ cycle cover giữa các vòng CEGAR trong cùng một
process. SAT repair, CRE--CEGAR
và wrapper Cardinality-CDCL lịch sử cũng chưa thuộc policy mặc định. Chúng chỉ nên
được thêm sau khi có:

1. kiểm thử đúng/sai trên tập nhỏ có đáp án độc lập;
2. timeout cứng và kiểm soát một luồng;
3. ablation cho thấy có unique win hoặc giảm thời gian có ý nghĩa;
4. log đủ để chỉ ra cơ chế nào tạo ra lợi ích.

Do đó benchmark tiếp theo có hai mục tiêu cần tách riêng. Nếu ưu tiên coverage,
chạy residual để thử hai HCup mode trên core 33. Nếu đánh giá phương pháp, chạy
ba baseline `ahs_cegar_only`, `ahs_hcup_outside_only` và `ahs_hcup_only` độc lập,
rồi mới so với `ahs_residual_v1`. Residual không thay thế HFP-only vì HFP chỉ nhận
35--40% tổng ngân sách và chạy sau outside.

Ba baseline độc lập có thể chạy bằng:

```bash
for AHS_VARIANT in ahs_cegar_only ahs_hcup_outside_only ahs_hcup_only; do
  python3 tools/hcp_benchmark.py \
    --config benchmarks/ahs_variants.json \
    --set historical_open_33 \
    --variants "$AHS_VARIANT" \
    --timeout 1800 \
    --output "benchmark-runs/${AHS_VARIANT}-open33-1800s"
done
```

Chạy tuần tự cả ba có trần 49,5 giờ. Nếu mục tiêu chỉ là tìm nghiệm mới trong
một ngày, ưu tiên wrapper residual; nếu mục tiêu là so sánh khoa học, cần đủ ba
baseline hoặc chia chúng sang các máy độc lập có cấu hình tương đương.

Nếu vẫn không có coverage mới, dùng
`portfolio_stage_results[].backend_activity` để phân biệt solver đang tiến triển
chậm, lặp model/subtour, hay gần như không backtrack. Khi đó mới chọn đúng chỗ để
tối ưu tiếp thay vì chỉ tăng timeout.
