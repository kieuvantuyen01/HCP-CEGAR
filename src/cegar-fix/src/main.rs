mod chained_lk;
mod contraction;
mod encoder;
mod file_operations;
mod graph;
mod hcp_solver;
mod hub_registry;
mod hub_sub_hcp;
mod ils_patcher;
mod macro_solver;
mod matching_patcher;
pub mod modular_solver;
pub mod modular_tree;
mod options;
mod parallel_sub_hcp;
mod patching;
pub mod stem_cycle_patcher;
pub mod two_tier_decomposer;
pub mod pinpointed_strip_solver;
pub mod global_demand_coordinator;
pub mod macro_splicer;
pub mod two_tier_orchestrator;
pub mod staged_subcycle_filter;
pub mod dual_cut_generator;
pub mod staged_lazy_smt_solver;
mod solver_outcome;

use contraction::Degree2Contractor;
use hub_registry::HubRegistry;
use std::time::Instant;
use log::info;
use solver_outcome::SolverOutcome;

fn main() {
    env_logger::init();
    info!("プログラム開始");
    let instant = Instant::now();

    let matches = options::get_options();

    // solver,encodingのオプションをintで受け取る
    let solver = matches.value_of_t::<i32>("solver").unwrap_or(0);
    let encoding = matches.value_of_t::<i32>("encoding").unwrap_or(0);
    let blocking = matches.value_of_t::<i32>("blocking").unwrap_or(0);
    let symmetry = matches.value_of_t::<i32>("symmetry").unwrap_or(0);
    let two_opt = matches.value_of_t::<i32>("2-opt").unwrap_or(0);
    let three_opt = matches.value_of_t::<i32>("three-opt").unwrap_or(0);
    let loop_prohibition = matches.value_of_t::<i32>("loop-prohibition").unwrap_or(0);
    let cnf_normalize = matches.value_of_t::<i32>("cnf-normalize").unwrap_or(0);
    let balanced = matches.value_of_t::<i32>("balanced").unwrap_or(0);
    let de_arcify = matches.value_of_t::<i32>("de-arcify").unwrap_or(0);
    let config = matches.value_of_t::<i32>("set-configration").unwrap_or(0);
    let degree_order = matches.value_of_t::<i32>("degree-order").unwrap_or(0);
    let arcs_order = matches.value_of_t::<i32>("arcs-order").unwrap_or(0);
    let cegar_fallback = matches.value_of_t::<i32>("cegar-fallback").unwrap_or(0);
    let mtz_stall = matches.value_of_t::<i32>("mtz-stall").unwrap_or(0);
    let adaptive_escalation = matches.value_of_t::<i32>("adaptive-escalation").unwrap_or(1);
    let sub_hcp_timeout = matches.value_of_t::<u64>("sub-hcp-timeout").unwrap_or(60);
    let max_cluster_size = matches.value_of_t::<usize>("max-cluster-size").unwrap_or(500);
    let is_two_tier = matches.is_present("two-tier") && matches.value_of("two-tier").map_or(true, |v| v != "0");
    let is_staged_smt = matches.is_present("staged-smt") && matches.value_of("staged-smt").map_or(true, |v| v != "0");
    let timeout_secs = matches.value_of_t::<f64>("timeout").unwrap_or(1800.0);
    let output_tour_path = matches.value_of("output-tour").map(|s| s.to_string());
    let degree2_triangle_prune = feature_enabled(&matches, "degree2-triangle-prune", true);
    let degree2_contraction = feature_enabled(&matches, "degree2-contraction", true);
    let features = hcp_solver::SolverFeatures {
        global_short_cuts: feature_enabled(&matches, "global-short-cuts", true),
        short_cycle_sec: feature_enabled(&matches, "short-cycle-sec", true),
        cluster_cuts: feature_enabled(&matches, "cluster-cuts", true),
        modular_prepass: feature_enabled(&matches, "modular-prepass", true),
        hub_partition_prepass: feature_enabled(&matches, "hub-partition-prepass", true),
        hub_patcher: feature_enabled(&matches, "hub-patcher", true),
        matching_patcher: feature_enabled(&matches, "matching-patcher", true),
        chained_lk: feature_enabled(&matches, "chained-lk", true),
        ils_patcher: feature_enabled(&matches, "ils-patcher", true),
        macro_patcher: feature_enabled(&matches, "macro-patcher", true),
        telemetry: feature_enabled(&matches, "telemetry", false),
    };
    // solver,encodingのオプションを&strで受け取る
    let input_filename = matches.value_of("input").unwrap_or("default");
    let output_foldername = matches.value_of("output").unwrap_or("default");

    println!("solve {}", input_filename);
    // let g = instance();
    let mut g = file_operations::input_to_graph(input_filename);
    let raw_g = g.clone();
    if de_arcify != 0{
        g.remove_redundant_arcs();
    }
    if is_staged_smt {
        let opt = staged_lazy_smt_solver::StagedLazySmtOptions {
            max_batch_size: 500,
            timeout_secs,
            output_path: output_tour_path.clone(),
        };
        let outcome = staged_lazy_smt_solver::solve_staged_lazy_smt(&g, &opt);
        emit_outcome(outcome, &raw_g, output_tour_path.as_deref(), instant);
        return;
    }
    if is_two_tier {
        let opt = two_tier_orchestrator::TwoTierSolverOptions {
            timeout_secs,
            max_iterations: 50_000,
            enable_patching: true,
            output_path: output_tour_path.clone(),
        };
        let outcome = two_tier_orchestrator::solve_graph_two_tier(&g, &opt);
        emit_outcome(outcome, &raw_g, output_tour_path.as_deref(), instant);
        return;
    }
    if g.has_articulation_points() {
        println!("Graph has cut-vertex or is disconnected.");
        emit_outcome(SolverOutcome::Unsat, &raw_g, output_tour_path.as_deref(), instant);
        return;
    }
    if degree2_triangle_prune {
        let pruned = g.prune_degree2_triangles();
        if pruned > 0 {
            println!("Pruned {} degree-2 triangle shortcut edges", pruned);
        }
    }
    let (contracted_g, contractor) = if degree2_contraction {
        Degree2Contractor::contract(&g)
    } else {
        (g.clone(), Degree2Contractor::identity(&g))
    };

    if let Some(cycle) = contractor.is_direct_cycle {
        println!("Graph is a single 2-regular Hamiltonian cycle.");
        emit_outcome(SolverOutcome::sat(cycle), &raw_g, output_tour_path.as_deref(), instant);
        return;
    }

    if contractor.is_infeasible {
        println!("Infeasible degree-2 structure detected.");
        emit_outcome(SolverOutcome::Unsat, &raw_g, output_tour_path.as_deref(), instant);
        return;
    }

    if contractor.contracted_vertices_count < contractor.original_vertices_count {
        println!(
            "Degree-2 contraction: compressed graph from {} to {} vertices (reduced by {}%)",
            contractor.original_vertices_count,
            contractor.contracted_vertices_count,
            (contractor.original_vertices_count - contractor.contracted_vertices_count) * 100 / contractor.original_vertices_count
        );
    }
    let hub_registry = HubRegistry::new(&contracted_g);
    if !hub_registry.hub_vertices.is_empty() {
        println!(
            "Dense Hub optimization: detected {} hub vertices (sample: {:?})",
            hub_registry.hub_vertices.len(),
            &hub_registry.hub_vertices[..hub_registry.hub_vertices.len().min(5)]
        );
    }
    let time1 = instant.elapsed();
    // println!("encodhing time = {:?} sec",instant.elapsed().as_secs());
    // let instant2 = Instant::now();

    // println!("solver={},encoding={}",solver,encoding);
    // println!("{:?}",g);
    println!("file input time = {:?}", time1);
    let outcome = hcp_solver::solve_hamilton(contracted_g, &contractor, &hub_registry, solver, encoding, blocking, symmetry, two_opt, loop_prohibition, cnf_normalize, balanced, de_arcify,config,degree_order,arcs_order,three_opt,cegar_fallback,mtz_stall,adaptive_escalation,sub_hcp_timeout,max_cluster_size,timeout_secs,instant,output_foldername, &features);
    let time2 = instant.elapsed() - time1;

    // println!("solving time = {:?} sec",instant2.elapsed().as_secs());
    println!("solving time = {:?}", time2);
    emit_outcome(outcome, &raw_g, output_tour_path.as_deref(), instant);
    info!("プログラム終了");
}

fn feature_enabled(matches: &clap::ArgMatches, name: &str, default: bool) -> bool {
    matches
        .value_of_t::<i32>(name)
        .map(|value| value != 0)
        .unwrap_or(default)
}

fn emit_outcome(
    outcome: SolverOutcome,
    raw_graph: &graph::Graph,
    output_tour_path: Option<&str>,
    instant: Instant,
) {
    match outcome {
        SolverOutcome::Sat(tour) => {
            if !macro_splicer::verify_tour_on_raw_graph(&tour, raw_graph) {
                println!("s ERROR");
                println!("c reason=independent_tour_verification_failed");
                println!("overall time = {:?}", instant.elapsed());
                return;
            }
            if let Some(path) = output_tour_path {
                if let Err(error) = two_tier_orchestrator::write_hcp_tour(&tour, path) {
                    println!("s ERROR");
                    println!("c reason=failed_to_write_tour detail={:?}", error);
                    println!("overall time = {:?}", instant.elapsed());
                    return;
                }
            }
            println!("solution:");
            println!("{}", tour.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(" "));
            println!("c certificate=verified_on_raw_graph vertices={}", tour.len());
            println!("s SATISFIABLE");
        }
        SolverOutcome::Unsat => println!("s UNSATISFIABLE"),
        SolverOutcome::Unknown(reason) => {
            println!("s UNKNOWN");
            println!("c reason={}", reason.replace(' ', "_"));
        }
        SolverOutcome::Error(reason) => {
            println!("s ERROR");
            println!("c reason={}", reason.replace(' ', "_"));
        }
    }
    println!("overall time = {:?}", instant.elapsed());
}

fn _instance() -> graph::Graph {
    let mut g = graph::Graph::new();
    g.add_edge(1, 2);
    g.add_edge(1, 8);
    g.add_edge(2, 3);
    g.add_edge(3, 4);
    g.add_edge(3, 7);
    g.add_edge(4, 5);
    g.add_edge(4, 6);
    g.add_edge(4, 8);
    g.add_edge(5, 6);
    g.add_edge(6, 7);
    g.add_edge(7, 8);
    g
}

// fn add_cl(lit_names: BTreeMap<Lit, String>, instance: &mut SatInstance) {
//     let mut map_i: BTreeMap<String, Vec<Lit>> = BTreeMap::new();
//     let mut map_j: BTreeMap<String, Vec<Lit>> = BTreeMap::new();

//     for (lit, name) in lit_names.iter() {
//         let parts: Vec<&str> = name.split("_").collect();
//         map_i.entry(parts[0].to_string()).or_insert(Vec::new()).push(lit.clone());
//         map_j.entry(parts[1].to_string()).or_insert(Vec::new()).push(lit.clone());
//     }

//     for (_, lits) in map_i.iter() {
//         for i in 0..lits.len() {
//             for j in i+1..lits.len() {
//                 instance.add_binary(!lits[i], !lits[j]);
//             }
//         }
//         instance.add_clause(lits.as_slice().into());
//     }

//     for (_, lits) in map_j.iter() {
//         for i in 0..lits.len() {
//             for j in i+1..lits.len() {
//                 instance.add_binary(!lits[i], !lits[j]);
//             }
//         }
//         instance.add_clause(lits.as_slice().into());
//     }
// }

// fn check_hamilton(edges: Vec<&str>) -> bool {
//     let mut graph: BTreeMap<&str,&str> = std::collections::BTreeMap::new();
//     for edge in edges {
//         let nodes: Vec<&str> = edge.split('_').collect();
//         let from = nodes[0];
//         let to = nodes[1];
//         graph.insert(from, to);
//     }

//     let start_node = graph.keys().next().unwrap();
//     let mut current_node = start_node;
//     let mut visited = std::collections::BTreeSet::new();
//     loop {
//         visited.insert(current_node);
//         current_node = match graph.get(current_node) {
//             Some(node) => node,
//             None => break,
//         };
//         if visited.contains(current_node) {
//             break;
//         }
//     }

//     visited.len() == graph.len() && current_node == start_node
// }

// fn solve_hamilton(lit_names: BTreeMap<Lit, String>,solver: &mut rustsat_minisat::core::Minisat){

//     let res = solver.solve().unwrap();
//     if res == SolverResult::Sat{
//         let sol = solver.full_solution().unwrap();
//         let true_lits: Vec<Lit> = lit_names.iter().filter_map(|(lit, _)| if sol[lit.var()] == TernaryVal::True { Some(lit.clone()) } else { None }).collect();
//         let true_lits_names: Vec<&str> = true_lits.iter().map(|lit| lit_names.get(lit).unwrap().as_str()).collect();
//         if check_hamilton(true_lits_names.clone()){
//             println!("{:?}",true_lits_names);
//         }else{
//             // let block_clause:Vec<Lit> = true_lits.iter().map(|&lit|!lit).collect();
//             let mut block_clause = rustsat::types::Clause::new();
//             for lit in true_lits.iter(){
//                 block_clause.add(!*lit);
//             }
//             // let block_clause:rustsat::types::Clause = true_lits.iter().collect();
//             let _ = solver.add_clause(block_clause);
//             solve_hamilton(lit_names,solver)
//         }
//     }else{
//         println!("UNSAT");
//     }

// }
