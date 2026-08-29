# AHS v0: cài đặt, cách chạy và giới hạn hiện tại

## 1. AHS v0 thực sự làm gì?

AHS v0 là một bộ điều phối có kiểm chứng cho các SAT solver HCP hiện có. Một lệnh AHS thực hiện bốn việc:

1. Đọc đồ thị và tính các đặc trưng đơn giản, tái lập được.
2. Chọn một lộ trình solver từ tệp chính sách cố định.
3. Chạy tuần tự các backend trong **một ngân sách thời gian tổng**.
4. Chỉ công nhận `SATISFIABLE` khi chu trình được kiểm tra độc lập trên đồ thị đầu vào.

Phiên bản này tích hợp ở mức tiến trình. CEGAR và HCup chưa truyền learned clauses hoặc cut-set trực tiếp cho nhau.

## 2. Thành phần đang bật

Chính sách mặc định `rule_v1` dùng:

- `paper_ccad_best_replay`: cấu hình CEGAR `-b 3 -y 3 -t 3 -l 1`;
- `hcup_hfp_preventsubcycle`: HCup với `merge-cutset`, refinement `outside` và propagator `prevent-subcycle`.

Ba nhóm đồ thị và phân bổ thử nghiệm là:

| Nhóm | Điều kiện | CEGAR | HCup-HFP |
|---|---|---:|---:|
| `dense` | `m/n >= 3` | 90% | 10% |
| `sparse_degree2` | `m/n < 3` và tỷ lệ đỉnh bậc 2 `> 10%` | 70% | 30% |
| `sparse_other` | còn lại | 80% | 20% |

Các tỷ lệ này là giả thuyết ban đầu cần đánh giá, không phải các giá trị tối ưu đã được chứng minh. Việc phân nhóm không dùng số hiệu instance và không tra kết quả biết trước. Cả hai ngưỡng phân nhóm nằm trong trường `routing` của `benchmarks/ahs_policy.json`; mọi lần chạy ghi lại config hash và các ngưỡng vào manifest.

## 3. Ngân sách thời gian

Mỗi stage nhận một **deadline tích lũy**. Ví dụ, lộ trình 80%–20% với ngân sách dùng cho backend là 100 giây:

- stage 1 có deadline ở giây 80;
- stage 2 có deadline ở giây 100.

Nếu stage 1 kết thúc sớm ở giây 30 nhưng chưa giải được, stage 2 được dùng phần còn lại đến giây 100. Vì vậy thời gian chưa dùng không bị mất. Nếu stage 1 tìm được nghiệm hợp lệ, AHS dừng ngay.

Mặc định AHS giữ lại 2 giây để dừng tiến trình, kiểm tra tour và ghi artifact. Thời gian đọc đặc trưng và điều phối được tính trong ngân sách; chỉ thời gian biên dịch backend nằm ngoài ngân sách giải.

## 4. Cài đặt và build

Cấu trúc thư mục mặc định là:

```text
parent/
├── HCP/     # repository này
└── hcup/    # mã nguồn HCup
```

Cần có Python 3, Rust/Cargo và CMake cùng một C++ compiler. Từ thư mục `HCP/` chạy:

Nếu chưa có HCup ở thư mục kề bên, clone bản đã sửa build portability:

```bash
git clone https://github.com/kieuvantuyen01/Hcup.git ../hcup
```

Sau đó build các backend:

```bash
./run_ahs.sh --build-only
```

Nếu các binary đã được build trên máy đó, thêm `--no-build` vào lệnh giải để AHS không kiểm tra build lại.

## 5. Chạy một instance

Xem trước lộ trình mà không cần binary:

```bash
./run_ahs.sh \
  --input FHCPCS-col/graph950.col \
  --policy rule_v1 \
  --timeout 1800 \
  --dry-run
```

Chạy thật trong ngân sách tổng 1.800 giây:

```bash
./run_ahs.sh \
  --input FHCPCS-col/graph950.col \
  --policy rule_v1 \
  --timeout 1800 \
  --output-tour graph950.ahs.tour \
  --no-build
```

Các policy kiểm soát có sẵn:

- `cegar_only`: chỉ chạy CEGAR;
- `hcup_only`: chỉ chạy HCup-HFP;
- `rule_v1`: lộ trình hai stage mặc định;
- `exploratory_v1`: thêm HCup không propagator ở stage thứ ba; chỉ dùng trong thí nghiệm có nhãn rõ.

## 6. Chạy tập 33 instance còn mở

Lệnh sau build backend một lần rồi chạy `historical_open_33`:

```bash
./run_ahs_benchmark.sh \
  --timeout 1800 \
  --output benchmark-runs/ahs-open33-1800s
```

Muốn chạy nền và có thể tiếp tục sau khi gián đoạn:

```bash
nohup ./run_ahs_benchmark.sh \
  --timeout 1800 \
  --output benchmark-runs/ahs-open33-1800s \
  --resume \
  > ahs-open33-1800s.console.log 2>&1 &
```

Tổng giới hạn trên là khoảng 16,5 giờ cho 33 instance ở 1.800 giây/instance; các instance giải sớm làm thời gian thực tế ngắn hơn. Grace 5 giây của benchmark runner chỉ dành cho AHS đóng tiến trình và ghi kết quả, không tăng ngân sách giải bên trong.

## 7. Kết quả và kiểm tra

Mỗi lần giải trực tiếp tạo một thư mục trong `ahs-runs/` gồm:

- `manifest.json`: graph hash, config hash, binary hash, policy, route và môi trường;
- `raw/`: stdout/stderr nguyên gốc của từng backend;
- `summary.json`: kết quả từng stage và kết quả cuối;
- `solution.tour`: chỉ có khi một tour đã vượt qua bộ kiểm tra độc lập.

Benchmark nhiều instance tiếp tục ghi `manifest.json`, `results.jsonl`, raw log và tour trong `benchmark-runs/`. Artifact nội bộ của mỗi lần AHS nằm trong `artifacts/<variant>/graphN-rR/` của chính benchmark run, nên có thể chép cả thư mục kết quả sang máy khác mà không mất provenance. Nếu tiếp tục một task từng bị ngắt trước khi ghi JSONL, runner giữ artifact cũ và tạo hậu tố `-attempt2`, `-attempt3`, v.v.; nó không dùng nhầm tour còn sót lại.

Quy tắc trạng thái cuối:

- SAT + tour hợp lệ: `s SATISFIABLE`, mã thoát 10;
- UNSAT từ backend được khai báo tin cậy: `s UNSATISFIABLE`, mã thoát 20;
- hết giờ hoặc không có kết luận: `s UNKNOWN`, mã thoát 0;
- backend báo SAT nhưng tour sai, hoặc lỗi cứng không được backend sau khắc phục: `s ERROR`, mã thoát 1.

Chạy test bằng:

```bash
python3 tools/test_ahs_solver.py
python3 tools/test_hybrid_coverage.py
```

## 8. Những gì chưa được cài đặt

Ba thành phần sau bị tắt có chủ ý và được ghi trong manifest:

- truyền cut/learned clause giữa CEGAR và HCup;
- SAT-repair;
- CRE-CEGAR làm preprocessing mặc định.

Lý do là CLI hiện tại chưa cung cấp giao diện trao đổi cut chung, còn SAT-repair và CRE-CEGAR chưa có cài đặt kèm kiểm thử tính đúng đủ mạnh. Không nên gộp chúng vào số liệu AHS trước khi hoàn thành hai điều kiện đó.
