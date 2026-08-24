use cegar_fix::graph::Graph;
use cegar_fix::macro_splicer::verify_tour_on_raw_graph;
use cegar_fix::two_tier_orchestrator::{solve_graph_two_tier, write_hcp_tour, TwoTierSolverOptions};
use cegar_fix::solver_outcome::SolverOutcome;
use std::fs;
use std::path::Path;

fn build_synthetic_graph() -> Graph {
    let mut g = Graph::new();
    // Auxiliary hubs 10..35 form a cycle with chords to give degree >= 20
    for i in 10..35 {
        g.add_edge(i, i + 1);
    }
    g.add_edge(35, 10);

    for i in 10..35 {
        for j in (i + 2)..=35 {
            if !(i == 10 && j == 35) {
                g.add_edge(i, j);
            }
        }
    }

    // 4 Hubs: 1, 2, 3, 4 connected to auxiliary hubs to have degree >= 20
    for i in 10..30 {
        g.add_edge(1, i);
        g.add_edge(2, i);
        g.add_edge(3, i);
        g.add_edge(4, i);
    }

    // Hub-Hub edges: (1, 2) and (3, 4)
    g.add_edge(1, 2);
    g.add_edge(3, 4);

    // Strip 1: 101-102-103
    g.add_edge(101, 102);
    g.add_edge(102, 103);
    g.add_edge(1, 101);
    g.add_edge(3, 103);

    // Strip 2: 201-202-203
    g.add_edge(201, 202);
    g.add_edge(202, 203);
    g.add_edge(2, 201);
    g.add_edge(4, 203);

    g
}

#[test]
fn test_synthetic_two_tier_orchestrator_solve() {
    let g = build_synthetic_graph();
    let temp_out = "target/test_synthetic_tour.hcp";
    if Path::new(temp_out).exists() {
        let _ = fs::remove_file(temp_out);
    }

    let options = TwoTierSolverOptions {
        timeout_secs: 60.0,
        max_iterations: 1000,
        enable_patching: true,
        output_path: Some(temp_out.to_string()),
    };

    let tour = match solve_graph_two_tier(&g, &options) {
        SolverOutcome::Sat(tour) => tour,
        other => panic!("expected SAT, got {:?}", other),
    };
    assert_eq!(tour.len(), g.adjacency_list.len());
    assert!(verify_tour_on_raw_graph(&tour, &g), "Tour must be verified on raw graph");
    assert!(Path::new(temp_out).exists(), "Output HCP tour file must be written");

    // Clean up
    let _ = fs::remove_file(temp_out);
}

#[test]
fn test_synthetic_two_tier_orchestrator_timeout() {
    let g = build_synthetic_graph();
    let options = TwoTierSolverOptions {
        timeout_secs: 0.000001,
        max_iterations: 0,
        enable_patching: true,
        output_path: None,
    };

    let result = solve_graph_two_tier(&g, &options);
    assert!(matches!(result, SolverOutcome::Unknown(_)), "Expected timeout / iteration limit to return UNKNOWN");
}

#[test]
fn test_write_hcp_tour_format() {
    let tour = vec![1, 2, 3, 4];
    let temp_out = "target/test_format_tour.hcp";
    if Path::new(temp_out).exists() {
        let _ = fs::remove_file(temp_out);
    }

    let res = write_hcp_tour(&tour, temp_out);
    assert!(res.is_ok());

    let content = fs::read_to_string(temp_out).unwrap();
    let lines: Vec<&str> = content.lines().collect();

    assert_eq!(lines[0], "NAME : hcp-solution");
    assert_eq!(lines[1], "TYPE : TOUR");
    assert_eq!(lines[2], "DIMENSION : 4");
    assert_eq!(lines[3], "TOUR_SECTION");
    assert_eq!(lines[4], "1");
    assert_eq!(lines[5], "2");
    assert_eq!(lines[6], "3");
    assert_eq!(lines[7], "4");
    assert_eq!(lines[8], "-1");
    assert_eq!(lines[9], "EOF");

    let _ = fs::remove_file(temp_out);
}
