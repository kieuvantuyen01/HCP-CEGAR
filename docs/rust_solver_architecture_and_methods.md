# Tài Liệu Kỹ Thuật: Kiến Trúc & Các Phương Pháp Trong Mã Nguồn Rust (`cegar-fix`)

> **Nguồn gốc & Tác quyền:** Mã nguồn bộ giải Rust `cegar-fix` được phát triển dựa trên công trình nghiên cứu và repository gốc của tác giả chính **Takehide Soh** (Kobe University, Japan) tại [`https://github.com/TakehideSoh/SAT-based-CEGAR`](https://github.com/TakehideSoh/SAT-based-CEGAR).

**Thư mục mã nguồn:** `src/cegar-fix/src/`  
**Tác giả chính:** Takehide Soh (Kobe University) & Các cộng tác viên  
**Repository gốc (Upstream):** [TakehideSoh/SAT-based-CEGAR](https://github.com/TakehideSoh/SAT-based-CEGAR)  
**Ngôn ngữ:** Rust (Sử dụng backend `rustsat` và solver native `rustsat-cadical` / CaDiCaL 1.9.4)  
**Mục đích:** Bộ giải tối ưu hóa bài toán Chu Trình Hamilton (Hamiltonian Cycle Problem - HCP) kết hợp phương pháp CEGAR, mã hóa SAT hiện đại và các kỹ thuật Heuristic Patching đa cấp.

---

## 1. Tổng Quan Kiến Trúc Mã Nguồn Rust

Hệ thống được tổ chức thành các mô-đun độc lập với luồng xử lý chính:

```
Graph Input (.col)
       │
       ▼
[contraction.rs] ─── Co rút chuỗi đỉnh bậc 2 (Degree-2 Contraction)
       │
       ▼
[encoder.rs] ─────── Mã hóa đồ thị sang CNF (Exact-2: Sinz, Adder, Binomial, Ladder)
       │              └─ [add_global_short_cycle_cuts]: Tiền xử lý chặn tam giác/tứ giác
       ▼
[hcp_solver.rs] ──── VÒNG LẶP CEGAR TRUNG TÂM (Incremental SAT Solving)
       │              ├─ [patching.rs]: 2-Opt & Restricted 3-Opt cycle merging
       │              ├─ [stem_cycle_patcher.rs]: Stem-based alternating path splicing
       │              ├─ [matching_patcher.rs]: Maximum bipartite matching merging
       │              ├─ [chained_lk.rs / ils_patcher.rs]: Lin-Kernighan & ILS local search
       │              ├─ [population_patcher.rs]: Edge-assembly giữa các SAT cycle cover
       │              ├─ [Partial MTZ Injection]: Bơm ràng buộc MTZ khi phát hiện stall
       │              └─ [Cut Blocking Clauses]: Sinh mệnh đề cắt (Cut / Subtour clauses)
       ▼
[modular_solver.rs] ─ Phân rã mô-đun vệ tinh (Satellite Modules) & Macro graph
       │
       ▼
Hamiltonian Cycle Output (.hcp / .tou) + Independent Verifier
```

---

## 2. Bảng Tra Cứu Tùy Chọn Dòng Lệnh (CLI Flags & Options)

| Cờ lệnh (Option) | Tên tham số | Giá trị hỗ trợ | Mô tả chi tiết chức năng |
|---|---|---|---|
| `-e, --encoding` | Mã hóa Exact-2 | `0`: Binomial (mặc định)<br>`1`: **Sinz Sequential Counter**<br>`2`: Adder Networks<br>`3`: Advanced Sinz<br>`4`: Product + Binomial<br>`5`: Recursive Product<br>`6`: Ladder Encoding | Lựa chọn phương pháp mã hóa ràng buộc $\sum_{e \in \delta(v)} x_e = 2$ cho từng đỉnh. `Sinz (-e 1)` cho hiệu năng CNF nhỏ gọn và lan truyền BCP nhanh nhất. |
| `-b, --block` | Chiến lược chặn cắt (Cut Blocking) | `0`: CEGAR truyền thống (chặn toàn bộ chu trình)<br>`1`: Gộp chung cung vào và cung ra vào 1 mệnh đề<br>`2`: Thêm cả mệnh đề gốc và option 1<br>`3`: **(Proposed) Tách cung cắt thành 2 mệnh đề riêng biệt**<br>`4`: Chỉ thêm cung cắt đi ra<br>`5`: Chỉ thêm cung cắt theo đỉnh có bậc cao nhất<br>`6..8`: Áp dụng CEGAR cũ cho chu trình $\le 3, 4, 5$ đỉnh<br>`9`: Chọn mệnh đề ngắn hơn giữa cũ và mới<br>`10`: Proposed kết hợp chặn cũ cho chu trình 3 đỉnh | Quyết định cấu trúc mệnh đề cắt (Cut Clause) sinh ra sau mỗi vòng CEGAR để ép chu trình con phải mở rộng. |
| `-t, --two-opt` | Mức độ 2-Opt Patching | `0`: Không dùng 2-opt<br>`1`: Chặn cả chu trình gốc lẫn chu trình đã ghép<br>`2`: Chặn chu trình gốc và chu trình ghép lớn nhất<br>`3`: **Chỉ chặn các chu trình sau khi ghép tối đa**<br>`4`: Dừng nếu có chu trình không ghép được và chặn tới điểm đó<br>`5`: Dừng ngay nếu có 1 chu trình không ghép được | Ghép các chu trình con rời rạc bằng các cặp cạnh chéo 2-opt trước khi phải sinh mệnh đề cắt nạp lại cho SAT. |
| `-x, --three-opt` | Restricted 3-Opt | `0`: Tắt (mặc định)<br>`1`: **Bật 3-Opt Candidate-Graph** | Mở rộng ghép chu trình 3 tầng qua chu trình trung gian khi 2-opt trực tiếp bị bế tắc. |
| `-y, --symmetry` | Phá vỡ đối xứng (Symmetry Breaking) | `0`: Không phá đối xứng<br>`1`: Chặn đối xứng cho đỉnh bậc nhỏ nhất<br>`2`: Chặn đối xứng cho đỉnh bậc lớn nhất<br>`3`: **Chặn đối xứng theo Support Vertex** | Ép hướng duyệt ban đầu của chu trình để loại bỏ tính đối xứng nghịch đảo $(u \rightarrow v \leftrightarrow v \rightarrow u)$. |
| `-l, --loop` | Cấm chu trình cực ngắn | `0`: Không cấm<br>`1`: **Cấm 2-chu trình (cạnh kép qua lại)**<br>`2`: Cấm 3-chu trình (tam giác)<br>`3`: Cấm cả 2-chu trình và 3-chu trình | Tiền mã hóa cấm trực tiếp các chu trình con siêu nhỏ ngay trong CNF khởi tạo. |
| `-A, --adaptive-escalation` | Leo thang thích ứng | `0`: Tắt<br>`1`: **Bật (mặc định)** | Tự động phát hiện khi bộ giải bị dậm chân tại chỗ (Stall) để nâng cấp chiến lược chặn từ mềm sang cứng. |
| `--mtz-stall <N>` | Bơm Miller-Tucker-Zemlin | `0`: Tắt<br>`N`: **Bơm ràng buộc MTZ sau N vòng stall** | Sinh biến thứ tự MTZ ($u_i$) và bất đẳng thức $u_i - u_j + n x_{ij} \le n - 1$ để phá vỡ bế tắc CEGAR. |
| `-f, --cegar-fallback` | Hard Blocking Fallback | `0`: Tắt<br>`1`: **Bật** | Dự phòng chặn cứng toàn bộ cấu hình cạnh khi các bộ vá heuristic không hội tụ. |
| `--population-patcher` | Population-guided recombination | `0`: Tắt (mặc định)<br>`1`: Bật treatment | Giữ tối đa 13 cycle cover SAT khác nhau; thử 2-opt/chained k-opt bằng cạnh của cover cha. Chỉ nhận cover hợp lệ có ít vòng hơn; không dùng heuristic để kết luận `UNSAT`. |

---

## 3. Chi Tiết Các Thuật Toán Trong Từng Module

---

### Module 1: `encoder.rs` — Mã Hóa CNF Đồ Thị & Ràng Buộc Bậc

- **Mã hóa Exact-2 bằng Sinz Sequential Counter (`-e 1`):**
  - Với mỗi đỉnh $v$ có $d$ cạnh kề $e_1, e_2, \dots, e_d$:
  - Tạo bảng biến đếm phụ trợ $s_{i, j}$ biểu diễn "đã có ít nhất $j$ cạnh được chọn trong số $i$ cạnh đầu tiên" ($1 \le j \le 2$).
  - Mệnh đề lan truyền đếm:
    $$\neg s_{i-1, j} \lor s_{i, j}$$
    $$\neg e_i \lor \neg s_{i-1, j-1} \lor s_{i, j}$$
  - Mệnh đề chặn trên At-Most-2: $\neg e_i \lor \neg s_{i-1, 2}$.
  - Mệnh đề chặn dưới At-Least-2: $s_{d, 2}$.
- **Hàm `add_global_short_cycle_cuts`:**
  - Quét trước toàn bộ đồ thị để phát hiện tất cả các tam giác (3-cycles) và tứ giác (4-cycles).
  - Thêm trước các mệnh đề cấm $\neg x_{uv} \lor \neg x_{vw} \lor \neg x_{wu}$ ngay trong CNF ban đầu nhằm triệt tiêu hàng trăm chu trình con ngắn trước khi SAT solver bắt đầu vòng lặp đầu tiên.

---

### Module 2: `hcp_solver.rs` — Vòng Lặp CEGAR & Cơ Chế Adaptive Escalation

- **Vòng lặp Incremental CEGAR:**
  1. Sử dụng `rustsat_cadical::CaDiCaL` duy trì solver trong bộ nhớ (In-Memory Incremental SAT).
  2. Mỗi lần giải ra một 2-Factor, đồ thị nghiệm được phân rã thành danh sách chu trình rời rạc $C_1, \dots, C_k$ bằng thuật toán duyệt BFS/DFS.
  3. Kích hoạt bộ lọc vá chu trình (`HubPatcher` 2-opt/3-opt).
  4. Nếu số chu trình sau vá $= 1 \rightarrow$ Kết thúc, tìm thấy chu trình Hamilton.
  5. Nếu còn $> 1$ chu trình $\rightarrow$ Sinh các mệnh đề cắt (Cut Clauses) theo tùy chọn `-b 3` và nạp tiếp vào solver mà không cần khởi động lại.
- **Cơ chế Partial MTZ Stall Injection (`--mtz-stall`):**
  - Theo dõi biến đếm `stall_count`: Nếu số lượng chu trình con không giảm qua $N$ vòng lặp liên tiếp, solver sẽ kích hoạt mã hóa thứ tự MTZ cục bộ cho các chu trình con bị tắc, ép buộc tính liên thông toàn cục bằng biến số nguyên/SAT.

---

### Module 3: `patching.rs` & `stem_cycle_patcher.rs` — Ghép Chu Trình Heuristic

- **`HubPatcher` (2-Opt & Restricted 3-Opt):**
  - Tìm kiếm cặp cạnh $(u_1, v_1) \in C_a$ và $(u_2, v_2) \in C_b$ sao cho $(u_1, u_2) \in E(G)$ và $(v_1, v_2) \in E(G)$.
  - Thay thế 2 cạnh cũ bằng 2 cạnh chéo để nối $C_a$ và $C_b$ thành 1 chu trình duy nhất trong $O(1)$.
  - Hỗ trợ **Restricted 3-Opt** thông qua đồ thị ứng viên (Candidate Graph) để nối 2 chu trình xa nhau thông qua 1 chu trình cầu nối thứ ba.
- **`StemCyclePatcher` (Stem Alternating Paths & Vertex Absorption):**
  - Thiết kế đặc thù cho các đồ thị có nhiều đỉnh bậc 2 bị cô lập (Class B2a/B2b).
  - Tìm các đường đi xen kẽ (Alternating Stems) bắt đầu từ một chu trình con, đi qua các đỉnh chưa được phủ hoặc chu trình khác, sau đó xoay vòng (cycle rotation) để nuốt các chu trình con nhỏ vào chu trình chính.

---

### Module 4: `matching_patcher.rs`, `chained_lk.rs` & `ils_patcher.rs` — Tối Ưu Cục Bộ Nâng Cao

- **`MatchingPatcher` (Maximum Weight Bipartite Matching):**
  - Xây dựng đồ thị phụ trợ giữa các chu trình con: Trọng số mỗi cạnh giữa $C_a$ và $C_b$ là số lượng cặp cạnh chéo 2-opt hợp lệ giữa chúng.
  - Giải bài toán Cặp ghép cực đại (Maximum Matching) để thực hiện hàng chục phép ghép 2-opt song song đồng thời trong 1 bước, tránh xung đột cạnh.
- **`ChainedLKSolver` (Chained Lin-Kernighan Heuristic):**
  - Triển khai giải thuật tìm kiếm cục bộ Lin-Kernighan với các bước nhảy $\lambda$-opt biến thiên.
  - Sử dụng cú hích **Double-Bridge Kick (4-opt perturbation)** để thoát khỏi các cực tiểu địa phương (local minima) khi chu trình đạt kích thước gần trọn vẹn.
- **`IteratedLocalSearchPatcher` (ILS):**
  - Kết hợp chu kỳ: *Local Search $\rightarrow$ Perturbation $\rightarrow$ Acceptance Criterion* để liên tục cải tiến độ dài của chu trình lớn nhất.
- **`PopulationPatcher` (treatment thực nghiệm):**
  - Chọn cover cha theo số cạnh nối chéo giữa các vòng hiện tại và độ đa dạng tập cạnh.
  - Recombination chỉ dùng cạnh trong hợp của hai cover; mọi offspring được kiểm tra lại trên graph trước khi sinh cut hoặc trả tour.
  - Baseline tái lập đặt `--population-patcher 0`. Chỉ bật cờ này trong A/B riêng cho đến khi có kết quả core-33 và easy-control.
  - Treatment dùng deadline chung của solver và hard cap 32 vòng luân phiên cho
    mỗi parent, 64 vòng guided matching và 32 vòng chained LK. Hết deadline trả
    `UNKNOWN`; chạm round cap chỉ dừng local search và CEGAR tiếp tục.
  - Telemetry báo riêng số vòng, `budget_exhausted` và `round_limit_hits` để phân
    biệt overhead do hết thời gian với việc local search hội tụ bình thường.
  - Sau các lần không cải thiện, backoff bỏ qua lần lượt 1, 3, 7, 15, 31 và tối
    đa 63 model; cover mới vẫn được lưu và `cooldown_skipped` ghi số lần bỏ qua.

---

### Module 5: `contraction.rs` — Co Rút Chuỗi Đỉnh Bậc 2 (Degree-2 Contraction)

- **Nguyên lý toán học:**
  - Nếu đỉnh $v$ có đúng 2 đỉnh kề $u$ và $w$ ($\text{deg}(v) = 2$), thì trong mọi chu trình Hamilton hợp lệ, 2 cạnh $(u, v)$ và $(v, w)$ **bắt buộc phải được chọn**.
  - Do đó, một chuỗi đỉnh bậc 2 liên tiếp: $u - v_1 - v_2 - \dots - v_k - w$ có thể được co rút (contract) thành đúng một siêu cạnh $(u, w)$ với trọng số chiều dài $k+1$.
- **Tác dụng:**
  - Giúp giảm tức thì 20%–40% số đỉnh của đồ thị trước khi chuyển giao sang SAT solver.
  - Sau khi solver tìm được chu trình trên đồ thị thu gọn, module sẽ thực hiện giải nén (expand) chuỗi đỉnh bậc 2 để khôi phục chu trình gốc 100% nguyên vẹn.

---

### Module 6: `modular_solver.rs`, `modular_tree.rs` & `macro_solver.rs` — Phân Rã Mô-Đun (Modular Decomposition)

- **Phân tách Đỉnh Hub và Vệ Tinh (Satellite Modules):**
  - Tách tập đỉnh đồ thị thành $V = \text{Hubs} \cup \text{Bulk}$.
  - Phân rã đồ thị con $G[\text{Bulk}]$ thành các thành phần liên thông độc lập (Satellite Modules / Strips).
  - Xây dựng cây phân rã mô-đun (`ModularDecompositionTree`) để quản lý các cổng kết nối biên (Boundary Nodes) giữa từng module với các Hubs.
- **Giải phân tầng (Two-Tier Decomposed HCP):**
  - **Tầng dưới (Sub-HCP):** Giải song song (`parallel_sub_hcp.rs`) tìm tập đường đi phủ đỉnh nội bộ cho từng module vệ tinh.
  - **Tầng trên (MacroGraphSolver):** Giải bài toán ghép nối vĩ mô trên các đỉnh Hub để tạo thành chu trình duy nhất đi qua toàn bộ các module.

---

## 4. Bảng Đề Xuất Cấu Hình Tối Ưu Theo Nhóm Đồ Thị (Benchmark Classes)

Dựa trên phân tích từ 1,001 bài toán benchmark FHCPCS:

| Nhóm Đồ Thị (Class) | Đặc trưng hình thái | Cấu hình cờ lệnh đề xuất |
|---|---|---|
| **Class A** (Attractor Loop, cycle count nhỏ) | Thưa, chu trình bị kẹt ở 2–6 chu trình khổng lồ | `./cegar-fix -i <file> -e 1 -b 3 -y 3 -l 1 -t 3 -x 1` |
| **Class B1** (Dense Hubs, $m/n \ge 3.0$) | Có nhiều đỉnh bậc cao ($\ge 50$), SAT call lâu | `./cegar-fix -i <file> -e 1 -b 3 -y 0 -t 3 -l 1 --three-opt 1` |
| **Class B2a** (Zero-Progress Merge Stall) | Thưa, nhiều đỉnh bậc 2, 2-opt thường bị tắc | `./cegar-fix -i <file> -e 1 -b 3 -y 0 -t 3 -l 1 --three-opt 1 --mtz-stall 5` |
| **Class B2b** (Expensive SAT Hardening) | Đỉnh bậc 2 rời rạc, SAT giải chậm dần theo thời gian | `./cegar-fix -i <file> -e 1 -b 3 -y 2 -t 3 -l 3 -A 1` |
