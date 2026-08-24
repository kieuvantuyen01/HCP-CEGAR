use std::time::Instant;
use crate::graph::Graph;
use crate::encoder::Encoder;
use crate::hcp_solver::add_global_short_cycle_cuts;
use crate::staged_subcycle_filter::StagedSubcycleFilter;
use crate::dual_cut_generator::DualCutGenerator;
use crate::macro_splicer::verify_tour_on_raw_graph;
use crate::two_tier_orchestrator::write_hcp_tour;
use crate::solver_outcome::SolverOutcome;
use rustsat::solvers::{ControlSignal, Solve, SolverResult, Terminate};
use rustsat::types::TernaryVal;
use rustsat_cadical::CaDiCaL;

pub struct StagedLazySmtOptions {
    pub max_batch_size: usize,
    pub timeout_secs: f64,
    pub output_path: Option<String>,
}

impl Default for StagedLazySmtOptions {
    fn default() -> Self {
        Self {
            max_batch_size: 500,
            timeout_secs: 1800.0,
            output_path: None,
        }
    }
}

pub fn solve_staged_lazy_smt(
    g: &Graph,
    options: &StagedLazySmtOptions,
) -> SolverOutcome {
    let start_time = Instant::now();
    let n = g.adjacency_list.len();

    println!("=== Starting Staged-Length Lazy SMT Solver in Rust ===");
    println!("Graph: {} vertices, {} arcs", n, g.arcs.len());

    // 1. Initial Sinz Base CNF Encoding
    let mut encoder = Encoder::new();
    let mut cnf = encoder.encode(g, 1, 0, 0, 0, 0, 0); // -e 1 (Sinz)

    // 2. Pre-prune 3-cycles (triangles)
    let added_triangles = add_global_short_cycle_cuts(g, &encoder, &mut cnf, 3);
    println!(
        "Initial base CNF generated in {:.2}s: {} clauses (pre-pruned {} triangles)",
        start_time.elapsed().as_secs_f64(),
        cnf.len(),
        added_triangles
    );

    // 3. Initialize CaDiCaL
    let mut solver = CaDiCaL::default();
    let _ = solver.add_cnf(cnf);
    let timeout_origin = start_time;
    let timeout_secs = options.timeout_secs;
    solver.attach_terminator(move || {
        if timeout_origin.elapsed().as_secs_f64() >= timeout_secs {
            ControlSignal::Terminate
        } else {
            ControlSignal::Continue
        }
    });

    let mut filter = StagedSubcycleFilter::new(options.max_batch_size);
    let mut iteration = 0;
    let mut total_cuts_added = 0;

    while start_time.elapsed().as_secs_f64() < options.timeout_secs {
        iteration += 1;
        let iter_start = Instant::now();

        let res = match solver.solve() {
            Ok(r) => r,
            Err(e) => {
                eprintln!("CaDiCaL solver error at iter {}: {:?}", iteration, e);
                return SolverOutcome::error(format!(
                    "CaDiCaL error at iteration {}: {:?}",
                    iteration, e
                ));
            }
        };

        let solve_dur = iter_start.elapsed().as_secs_f64();

        match res {
            SolverResult::Sat => {
                // Extract active arcs
                let sol = match solver.full_solution() {
                    Ok(s) => s,
                    Err(e) => {
                        eprintln!("Failed to get full solution at iter {}: {:?}", iteration, e);
                        return SolverOutcome::error(format!(
                            "failed to read CaDiCaL model at iteration {}: {:?}",
                            iteration, e
                        ));
                    }
                };
                let mut active_arcs = Vec::new();
                for (&(u, v), &lit) in &encoder.graph_lit_map {
                    if sol.lit_value(lit) == TernaryVal::True {
                        active_arcs.push((u, v));
                    }
                }

                let subcycles = StagedSubcycleFilter::extract_subcycles(&active_arcs);

                if subcycles.len() == 1 && subcycles[0].vertices.len() == n {
                    let tour = &subcycles[0].vertices;
                    println!(
                        "SUCCESS! Found single Hamiltonian tour with {} vertices at iter {} ({:.2}s total)!",
                        tour.len(),
                        iteration,
                        start_time.elapsed().as_secs_f64()
                    );
                    if verify_tour_on_raw_graph(tour, g) {
                        println!("CERTIFICATION PASSED: Verified tour independently on raw graph G!");
                        if let Some(out_path) = options.output_path.as_deref() {
                            if let Err(e) = write_hcp_tour(tour, out_path) {
                                eprintln!("Warning: failed to write tour to {}: {}", out_path, e);
                            } else {
                                println!("Wrote certified tour to {}", out_path);
                            }
                        }
                        return SolverOutcome::sat(tour.clone());
                    } else {
                        eprintln!("Verification failed on raw graph.");
                        return SolverOutcome::error("independent tour verification failed");
                    }
                }

                // Filter candidates matching current K_stage
                let active_cycles = filter.filter_active_cycles(&subcycles, n);
                if active_cycles.is_empty() {
                    eprintln!("Warning: No active cycles to cut at iter {}", iteration);
                    return SolverOutcome::error(format!(
                        "no active subcycle was available at iteration {}",
                        iteration
                    ));
                }

                let mut added_this_round = 0;
                for cyc in &active_cycles {
                    let cuts = DualCutGenerator::generate_dual_cuts(cyc, g, &encoder);
                    for cl in cuts {
                        let _ = solver.add_clause(cl);
                        added_this_round += 1;
                        total_cuts_added += 1;
                    }
                }

                if iteration <= 10 || iteration % 20 == 0 || active_cycles.len() == 1 {
                    println!(
                        "Iter {}: SAT ({:.2}s) | {} subcycles (min len {}, max len {}) | Stage K<={} | Added {} cuts (total {}) | {:.1}s elapsed",
                        iteration,
                        solve_dur,
                        subcycles.len(),
                        subcycles.first().map_or(0, |c| c.vertices.len()),
                        subcycles.last().map_or(0, |c| c.vertices.len()),
                        filter.k_stage,
                        added_this_round,
                        total_cuts_added,
                        start_time.elapsed().as_secs_f64()
                    );
                }
            }
            SolverResult::Unsat => {
                println!(
                    "Solver returned UNSAT at iter {} ({:.2}s). Graph has no Hamiltonian cycle.",
                    iteration,
                    start_time.elapsed().as_secs_f64()
                );
                return SolverOutcome::Unsat;
            }
            SolverResult::Interrupted => {
                println!("Solver interrupted at iter {}.", iteration);
                let reason = if start_time.elapsed().as_secs_f64() >= options.timeout_secs {
                    format!("strict in-process timeout at iteration {}", iteration)
                } else {
                    format!("CaDiCaL interrupted at iteration {}", iteration)
                };
                return SolverOutcome::unknown(reason);
            }
        }
    }

    println!(
        "[TIMEOUT] Reached {:.1}s timeout after {} iterations ({} total cuts added).",
        options.timeout_secs, iteration, total_cuts_added
    );
    SolverOutcome::unknown(format!(
        "cooperative timeout after {} iterations and {} cuts",
        iteration, total_cuts_added
    ))
}
