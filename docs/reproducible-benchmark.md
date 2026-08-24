# Thực nghiệm tái lập và khoanh vùng regression

Tài liệu này mô tả quy trình chạy HCP trên một máy khác theo cách có thể đối chiếu với mã nguồn gốc và truy nguyên từng cải tiến. Runner chỉ dùng thư viện chuẩn Python, không phụ thuộc lệnh GNU `timeout`, và mọi đường dẫn đều được suy ra từ vị trí repository.

## 1. Yêu cầu môi trường

- Python 3.10 trở lên.
- Rust stable (`rustc` và `cargo`).
- Trình biên dịch C/C++ cho CaDiCaL (`build-essential` trên Ubuntu hoặc Command Line Tools trên macOS).
- Hai repository `HCP/` và `SAT-based-CEGAR/` nằm cạnh nhau nếu muốn build/chạy baseline gốc. Runner copy source baseline sang thư mục run trước khi build nên không sinh `Cargo.lock` hay artifact trong repository gốc. Chỉ cần `HCP/` nếu chỉ chạy các variant cải tiến.

Kiểm tra nhanh:

```bash
python3 --version
rustc --version
cargo --version
```

## 2. Trạng thái kết quả và tính đúng

Binary cải tiến chỉ in đúng một trạng thái cuối:

- `s SATISFIABLE`: có tour và tour đã được kiểm tra độc lập trên đồ thị gốc.
- `s UNSATISFIABLE`: solver đã chứng minh UNSAT.
- `s UNKNOWN`: timeout, bị interrupt, hoặc hết giới hạn vòng lặp; không được tính là UNSAT.
- `s ERROR`: lỗi solver, lỗi lấy model, lỗi ghi certificate, hoặc certificate không hợp lệ.

Solver chính và staged solver gắn callback terminator vào CaDiCaL nên timeout được kiểm tra cả bên trong một SAT call dài. Các heuristic/prepass vẫn chỉ kiểm tra theo phase. Runner Python vì vậy luôn áp dụng thêm timeout cứng ở cấp process group để bảo vệ toàn bộ tiến trình, kể cả lỗi native hoặc một heuristic chạy quá lâu.

Với mọi kết quả SAT, runner đọc tour, kiểm tra số đỉnh, tính duy nhất của đỉnh, và mọi cạnh liên tiếp (kể cả cạnh đóng chu trình). Kết quả không qua kiểm tra được đổi thành `INVALID_SAT`.

## 3. Chạy thử

Từ thư mục `HCP`:

```bash
./run_tests.sh
```

Lệnh này build baseline gốc, bản base đã tắt cải tiến, và bản full; sau đó chạy năm graph smoke với timeout cứng 120 giây.

Nếu baseline gốc không có trên máy, chỉ chạy mã trong repository này:

```bash
python3 tools/hcp_benchmark.py \
  --variants current_base,current_full \
  --set smoke \
  --timeout 120
```

## 4. Ma trận ablation

Các variant nằm trong `benchmarks/ablation_variants.json`. `current_base` tắt toàn bộ phần mới bằng cờ thực, sau đó mỗi variant chỉ bật một nhóm:

- `plus_3opt`
- `plus_short_cuts`
- `plus_degree2`
- `plus_cluster_cuts`
- `plus_hub_patcher`
- `plus_matching_patcher`
- `plus_chained_lk`
- `plus_ils_patcher`
- `plus_macro_patcher`
- `plus_dense_prepasses`
- `fallback_mtz`
- `adaptive_escalation`
- `current_full`

Chạy trước trên tập đã khoanh vùng (13 regression, 2 win, Class A, dense core và B2a):

```bash
python3 tools/hcp_benchmark.py \
  --set regression_core \
  --timeout 1800 \
  --shuffle \
  --repetitions 3 \
  --output benchmark-runs/regression-core
```

Có thể tiếp tục một run bị dừng mà không chạy lại các cặp đã xong:

```bash
python3 tools/hcp_benchmark.py \
  --set regression_core \
  --timeout 1800 \
  --shuffle \
  --repetitions 3 \
  --output benchmark-runs/regression-core \
  --resume
```

Để chạy 100 graph lấy mẫu hoặc toàn bộ 1.001 graph:

```bash
python3 tools/hcp_benchmark.py --set sample_100 --variants paper_upstream,current_full
./run_fhcpcs_sota.sh
```

Không nên chạy toàn bộ 15 variant trên 1.001 graph ngay từ đầu. Chọn các variant thắng qua regression core và sample 100, rồi mới chạy full benchmark.

## 5. Artifact của mỗi run

Mỗi thư mục run chứa:

- `manifest.json`: commit/dirty state, hash binary và config, phiên bản toolchain, host, biến môi trường, danh sách graph và lệnh đầy đủ.
- `results.jsonl`: một record cho mỗi `(variant, graph, repetition)`; ghi status, wall time, feature đồ thị, số increment/clause, verification, conflicts/decisions/propagations và thống kê tổng hợp từng patcher.
- `raw/<variant>/`: stdout/stderr đầy đủ.
- `tours/<variant>/`: certificate SAT.

Các dòng telemetry có dạng:

```text
c metric phase=matching_patcher iteration=17 seconds=0.012 cycles_before=42 cycles_after=31
```

Nhờ vậy có thể phân biệt thời gian CaDiCaL, overhead của từng patcher, và patcher có thực sự giảm số chu trình con hay không. JSONL giữ tổng số call/thời gian/mức giảm chu trình theo phase; diễn biến từng iteration được giữ trong raw log để JSONL không phình quá lớn.

## 6. Phân tích paired, PAR và so với CSV bài báo

So bản full với baseline chạy cùng máy:

```bash
python3 tools/analyze_benchmark.py \
  benchmark-runs/regression-core/results.jsonl \
  --baseline paper_upstream \
  --candidate current_full \
  --par-factor 2 \
  --output benchmark-runs/regression-core/analysis.md
```

So với cấu hình đơn tốt nhất trong CSV Sinz của bài báo (937 solved):

```bash
python3 tools/analyze_benchmark.py \
  benchmark-runs/regression-core/results.jsonl \
  --candidate current_full \
  --paper-csv data/proposed-cegar-sinz-cpu.csv \
  --paper-column asp2-fix-2loop-2opt3-cadical-sinz \
  --output benchmark-runs/regression-core/analysis-vs-paper.md
```

Báo cáo dùng paired gains/regressions, geometric mean và median ratio trên các graph cùng solved, PAR-2 (hoặc PAR khác qua `--par-factor`), đồng thời chia graph thành `dense`, `sparse_degree2`, và `sparse_other`.

Thời gian trong CSV bài báo được đo trên máy khác, nên danh sách solved/timeout có thể dùng để khoanh vùng; tỷ lệ runtime chỉ nên kết luận từ các run paired trên cùng host, cùng timeout và cùng số thread.

## 7. Kiểm tra riêng một certificate

```bash
python3 tools/verify_tour.py \
  FHCPCS-col/graph950.col \
  benchmark-runs/full/tours/current_full/graph950-r1.hcp.tour
```

Exit code là 0 khi hợp lệ và 1 khi không hợp lệ.

## 8. Cờ ablation trong binary

Mỗi cờ nhận `0` hoặc `1`: `--degree2-triangle-prune`, `--degree2-contraction`, `--global-short-cuts`, `--short-cycle-sec`, `--cluster-cuts`, `--modular-prepass`, `--hub-partition-prepass`, `--hub-patcher`, `--matching-patcher`, `--chained-lk`, `--ils-patcher`, `--macro-patcher`, và `--telemetry`.

`--cegar-fallback`, `--mtz-stall`, `--adaptive-escalation`, `--sub-hcp-timeout`, và `--max-cluster-size` đã được nối lại vào vòng CEGAR. File cấu hình ablation luôn truyền giá trị tường minh để một thay đổi default trong tương lai không làm sai provenance.
