use crate::contraction::Degree2Contractor;
use crate::graph::Graph;
use crate::hub_registry::HubRegistry;
use std::collections::HashMap;
use std::time::Instant;

/// Lin-Kernighan / Variable-Depth Chained k-Opt Patcher.
///
/// Discovers alternating closed walks across 3 to `max_depth` subcycles
/// to break out of topological local minima without invoking SAT solver.
pub struct ChainedLKSolver;

/// Result of a deadline-aware chained LK call.
#[derive(Clone, Debug)]
pub struct BoundedChainedLKResult {
    pub cycles: Vec<Vec<i32>>,
    pub iterations: usize,
    pub budget_exhausted: bool,
    pub round_limit_reached: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TraversalDirection {
    Forward,
    Reverse,
}

#[derive(Clone, Debug)]
struct ChainStep {
    cycle_idx: usize,
    entry: i32,
    exit: i32,
    pos: usize,
    dir: TraversalDirection,
}

impl ChainedLKSolver {
    /// Iteratively applies Chained k-Opt merges until convergence or single cycle.
    pub fn patch_cycles_via_chained_lk(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
    ) -> Vec<Vec<i32>> {
        Self::patch_cycles(
            cycles,
            g,
            contractor,
            hub_registry,
            max_depth,
            cycles.len().saturating_mul(2),
            None,
        )
        .cycles
    }

    /// Apply chained LK with an explicit iteration cap and absolute deadline.
    ///
    /// Population-guided CEGAR uses this entry point so local search cannot keep
    /// running after the solver's global budget has expired. The historical
    /// unbounded-by-time entry point above is retained for the other backends.
    pub fn patch_cycles_via_chained_lk_bounded(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
        max_iterations: usize,
        deadline: Instant,
    ) -> BoundedChainedLKResult {
        Self::patch_cycles(
            cycles,
            g,
            contractor,
            hub_registry,
            max_depth,
            max_iterations,
            Some(deadline),
        )
    }

    fn patch_cycles(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
        max_iterations: usize,
        deadline: Option<Instant>,
    ) -> BoundedChainedLKResult {
        if cycles.len() < 3 || max_depth < 3 {
            return BoundedChainedLKResult {
                cycles: cycles.to_vec(),
                iterations: 0,
                budget_exhausted: deadline_reached(deadline),
                round_limit_reached: false,
            };
        }

        let mut current_cycles = cycles.to_vec();
        let mut iterations = 0;
        let mut budget_exhausted = false;
        let mut converged = false;

        for _ in 0..max_iterations {
            if deadline_reached(deadline) {
                budget_exhausted = true;
                break;
            }
            if current_cycles.len() < 3 {
                converged = true;
                break;
            }

            iterations += 1;
            let mut search_budget_exhausted = false;
            if let Some((used_indices, merged)) = Self::find_alternating_chain_until(
                &current_cycles,
                g,
                contractor,
                hub_registry,
                max_depth,
                deadline,
                &mut search_budget_exhausted,
            )
            {
                let mut used = vec![false; current_cycles.len()];
                for &idx in &used_indices {
                    used[idx] = true;
                }

                let mut next_cycles = Vec::with_capacity(current_cycles.len() - used_indices.len() + 1);
                next_cycles.push(merged);
                for (idx, c) in current_cycles.into_iter().enumerate() {
                    if !used[idx] {
                        next_cycles.push(c);
                    }
                }
                current_cycles = next_cycles;
            } else {
                budget_exhausted = search_budget_exhausted;
                converged = !search_budget_exhausted;
                break;
            }
        }

        BoundedChainedLKResult {
            cycles: current_cycles,
            iterations,
            budget_exhausted,
            round_limit_reached: !budget_exhausted
                && !converged
                && max_iterations > 0
                && iterations == max_iterations,
        }
    }

    /// Searches for an alternating chain across a subset of subcycles and returns the merged cycle.
    pub fn search_alternating_chain(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
    ) -> Option<Vec<i32>> {
        Self::find_alternating_chain(cycles, g, contractor, hub_registry, max_depth)
            .map(|(_, merged)| merged)
    }

    /// Internal search returning both the merged cycle and the cycle indices that were combined.
    fn find_alternating_chain(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
    ) -> Option<(Vec<usize>, Vec<i32>)> {
        let mut budget_exhausted = false;
        Self::find_alternating_chain_until(
            cycles,
            g,
            contractor,
            hub_registry,
            max_depth,
            None,
            &mut budget_exhausted,
        )
    }

    fn find_alternating_chain_until(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
        deadline: Option<Instant>,
        budget_exhausted: &mut bool,
    ) -> Option<(Vec<usize>, Vec<i32>)> {
        let n = cycles.len();
        if n < 3 || max_depth < 3 {
            return None;
        }

        let effective_max_depth = max_depth.min(n);

        // Map vertex -> (cycle_index, position_in_cycle)
        let mut vertex_to_cycle: HashMap<i32, (usize, usize)> = HashMap::new();
        for (c_idx, c) in cycles.iter().enumerate() {
            for (pos, &v) in c.iter().enumerate() {
                vertex_to_cycle.insert(v, (c_idx, pos));
            }
        }

        let mut visited = vec![false; n];
        let mut path_stack = Vec::with_capacity(effective_max_depth);

        for start_idx in 0..n {
            if deadline_reached(deadline) {
                *budget_exhausted = true;
                return None;
            }
            let start_cycle = &cycles[start_idx];
            let len0 = start_cycle.len();
            if len0 < 3 {
                continue;
            }

            visited[start_idx] = true;

            for p in 0..len0 {
                if deadline_reached(deadline) {
                    visited[start_idx] = false;
                    *budget_exhausted = true;
                    return None;
                }
                // Forward orientation:
                // entry = start_cycle[p], exit = start_cycle[(p + len0 - 1) % len0]
                // broken edge = (exit, entry)
                let entry_fwd = start_cycle[p];
                let exit_fwd = start_cycle[(p + len0 - 1) % len0];
                if is_safe_to_break(exit_fwd, entry_fwd, contractor) {
                    path_stack.push(ChainStep {
                        cycle_idx: start_idx,
                        entry: entry_fwd,
                        exit: exit_fwd,
                        pos: p,
                        dir: TraversalDirection::Forward,
                    });

                    if let Some(res) = Self::dfs_alternating_chain(
                        cycles,
                        g,
                        contractor,
                        hub_registry,
                        effective_max_depth,
                        &vertex_to_cycle,
                        &mut visited,
                        &mut path_stack,
                        deadline,
                        budget_exhausted,
                    ) {
                        return Some(res);
                    }

                    path_stack.pop();
                    if *budget_exhausted {
                        visited[start_idx] = false;
                        return None;
                    }
                }

                // Reverse orientation:
                // entry = start_cycle[p], exit = start_cycle[(p + 1) % len0]
                // broken edge = (entry, exit)
                let entry_rev = start_cycle[p];
                let exit_rev = start_cycle[(p + 1) % len0];
                if is_safe_to_break(entry_rev, exit_rev, contractor) {
                    path_stack.push(ChainStep {
                        cycle_idx: start_idx,
                        entry: entry_rev,
                        exit: exit_rev,
                        pos: p,
                        dir: TraversalDirection::Reverse,
                    });

                    if let Some(res) = Self::dfs_alternating_chain(
                        cycles,
                        g,
                        contractor,
                        hub_registry,
                        effective_max_depth,
                        &vertex_to_cycle,
                        &mut visited,
                        &mut path_stack,
                        deadline,
                        budget_exhausted,
                    ) {
                        return Some(res);
                    }

                    path_stack.pop();
                    if *budget_exhausted {
                        visited[start_idx] = false;
                        return None;
                    }
                }
            }

            visited[start_idx] = false;
        }

        None
    }

    fn dfs_alternating_chain(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        max_depth: usize,
        vertex_to_cycle: &HashMap<i32, (usize, usize)>,
        visited: &mut [bool],
        path_stack: &mut Vec<ChainStep>,
        deadline: Option<Instant>,
        budget_exhausted: &mut bool,
    ) -> Option<(Vec<usize>, Vec<i32>)> {
        if deadline_reached(deadline) {
            *budget_exhausted = true;
            return None;
        }
        let current_depth = path_stack.len();
        let last_step = path_stack.last().unwrap();
        let exit_v = last_step.exit;
        let start_entry = path_stack[0].entry;

        let Some(neighbors) = g.adjacency_list.get(&exit_v) else {
            return None;
        };

        // Check if loop closure back to start_entry is possible (requires >= 3 cycles)
        if current_depth >= 3 && neighbors.contains(&start_entry) {
            let merged = splice_chain(cycles, path_stack);
            if is_valid_cycle(&merged, g) {
                let used_indices: Vec<usize> = path_stack.iter().map(|s| s.cycle_idx).collect();
                return Some((used_indices, merged));
            }
        }

        if current_depth < max_depth {
            for &nbr in neighbors {
                if deadline_reached(deadline) {
                    *budget_exhausted = true;
                    return None;
                }
                if let Some(&(next_idx, pos_nbr)) = vertex_to_cycle.get(&nbr) {
                    if !visited[next_idx] {
                        let next_cycle = &cycles[next_idx];
                        let len_next = next_cycle.len();
                        if len_next < 3 {
                            continue;
                        }

                        // Forward traversal in next_cycle
                        let exit_fwd = next_cycle[(pos_nbr + len_next - 1) % len_next];
                        if is_safe_to_break(exit_fwd, nbr, contractor) {
                            visited[next_idx] = true;
                            path_stack.push(ChainStep {
                                cycle_idx: next_idx,
                                entry: nbr,
                                exit: exit_fwd,
                                pos: pos_nbr,
                                dir: TraversalDirection::Forward,
                            });

                            if let Some(res) = Self::dfs_alternating_chain(
                                cycles,
                                g,
                                contractor,
                                hub_registry,
                                max_depth,
                                vertex_to_cycle,
                                visited,
                                path_stack,
                                deadline,
                                budget_exhausted,
                            ) {
                                return Some(res);
                            }

                            path_stack.pop();
                            visited[next_idx] = false;
                            if *budget_exhausted {
                                return None;
                            }
                        }

                        // Reverse traversal in next_cycle
                        let exit_rev = next_cycle[(pos_nbr + 1) % len_next];
                        if is_safe_to_break(nbr, exit_rev, contractor) {
                            visited[next_idx] = true;
                            path_stack.push(ChainStep {
                                cycle_idx: next_idx,
                                entry: nbr,
                                exit: exit_rev,
                                pos: pos_nbr,
                                dir: TraversalDirection::Reverse,
                            });

                            if let Some(res) = Self::dfs_alternating_chain(
                                cycles,
                                g,
                                contractor,
                                hub_registry,
                                max_depth,
                                vertex_to_cycle,
                                visited,
                                path_stack,
                                deadline,
                                budget_exhausted,
                            ) {
                                return Some(res);
                            }

                            path_stack.pop();
                            visited[next_idx] = false;
                            if *budget_exhausted {
                                return None;
                            }
                        }
                    }
                }
            }
        }

        None
    }
}

#[inline]
fn deadline_reached(deadline: Option<Instant>) -> bool {
    deadline.map_or(false, |limit| Instant::now() >= limit)
}

fn splice_chain(cycles: &[Vec<i32>], path_stack: &[ChainStep]) -> Vec<i32> {
    let total_len: usize = path_stack.iter().map(|s| cycles[s.cycle_idx].len()).sum();
    let mut merged = Vec::with_capacity(total_len);

    for step in path_stack {
        let cycle = &cycles[step.cycle_idx];
        let len = cycle.len();
        let pos = step.pos;

        match step.dir {
            TraversalDirection::Forward => {
                for s in 0..len {
                    merged.push(cycle[(pos + s) % len]);
                }
            }
            TraversalDirection::Reverse => {
                for s in 0..len {
                    merged.push(cycle[(pos + len - (s % len)) % len]);
                }
            }
        }
    }

    merged
}

#[inline]
fn is_safe_to_break(u: i32, v: i32, contractor: &Degree2Contractor) -> bool {
    !contractor.chain_map.contains_key(&(u, v)) && !contractor.chain_map.contains_key(&(v, u))
}

#[inline]
fn has_edge(g: &Graph, u: i32, v: i32) -> bool {
    g.adjacency_list.get(&u).map_or(false, |adj| adj.contains(&v))
}

fn is_valid_cycle(cycle: &[i32], g: &Graph) -> bool {
    let len = cycle.len();
    if len < 3 {
        return false;
    }
    for i in 0..len {
        let u = cycle[i];
        let v = cycle[(i + 1) % len];
        if !has_edge(g, u, v) {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contraction::Degree2Contractor;
    use crate::graph::Graph;
    use crate::hub_registry::HubRegistry;
    use std::collections::HashMap;
    use std::time::Duration;

    fn build_test_graph(edges: &[(i32, i32)]) -> Graph {
        let mut g = Graph::new();
        for &(u, v) in edges {
            g.add_edge(u, v);
        }
        g
    }

    fn empty_contractor() -> Degree2Contractor {
        Degree2Contractor {
            chain_map: HashMap::new(),
            original_vertices_count: 0,
            contracted_vertices_count: 0,
            is_direct_cycle: None,
            is_infeasible: false,
        }
    }

    fn empty_hub_registry() -> HubRegistry {
        HubRegistry {
            is_hub: Vec::new(),
            hub_vertices: Vec::new(),
            hub_neighbors: HashMap::new(),
            min_hub_degree: 3,
        }
    }

    #[test]
    fn test_chained_lk_4cycle_alternating_loop() {
        // 4 subcycles arranged in a bridge loop where no 2-cycle 2-opt or 3-cycle 3-opt works,
        // but a 4-cycle chained LK merge successfully merges all 4 cycles into 1.
        //
        // Cycle 0: 1 - 2 - 3 - 4 - 1
        // Cycle 1: 5 - 6 - 7 - 8 - 5
        // Cycle 2: 9 - 10 - 11 - 12 - 9
        // Cycle 3: 13 - 14 - 15 - 16 - 13
        //
        // Cross edges:
        // (2, 5)   - from Cycle 0 to Cycle 1
        // (6, 9)   - from Cycle 1 to Cycle 2
        // (10, 13) - from Cycle 2 to Cycle 3
        // (14, 1)  - from Cycle 3 to Cycle 0
        let edges = vec![
            // Cycle 0
            (1, 2), (2, 3), (3, 4), (4, 1),
            // Cycle 1
            (5, 6), (6, 7), (7, 8), (8, 5),
            // Cycle 2
            (9, 10), (10, 11), (11, 12), (12, 9),
            // Cycle 3
            (13, 14), (14, 15), (15, 16), (16, 13),
            // Bridge cross edges
            (2, 5),
            (6, 9),
            (10, 13),
            (14, 1),
        ];

        let g = build_test_graph(&edges);
        let contractor = empty_contractor();
        let hub_registry = empty_hub_registry();

        let cycles = vec![
            vec![1, 2, 3, 4],
            vec![5, 6, 7, 8],
            vec![9, 10, 11, 12],
            vec![13, 14, 15, 16],
        ];

        // 1. search_alternating_chain directly finds the 4-cycle merge
        let merged_opt = ChainedLKSolver::search_alternating_chain(&cycles, &g, &contractor, &hub_registry, 4);
        assert!(merged_opt.is_some(), "Should find alternating 4-cycle merge");
        let merged = merged_opt.unwrap();
        assert_eq!(merged.len(), 16, "Merged cycle must contain all 16 vertices");
        assert!(is_valid_cycle(&merged, &g), "Merged cycle must be valid in G");

        // 2. patch_cycles_via_chained_lk reduces 4 cycles to 1
        let patched = ChainedLKSolver::patch_cycles_via_chained_lk(&cycles, &g, &contractor, &hub_registry, 4);
        assert_eq!(patched.len(), 1, "Should merge all 4 cycles into 1");
        assert_eq!(patched[0].len(), 16);
        assert!(is_valid_cycle(&patched[0], &g));
    }

    #[test]
    fn test_chained_lk_full_convergence() {
        // Multi-round convergence test:
        // 3 triplets of subcycles (9 subcycles total, 27 vertices).
        // Each triplet has internal cross edges forming a 3-cycle alternating loop.
        // Inter-triplet cross edges form a high-level 3-cycle loop between the merged groups.
        let mut edges = Vec::new();

        // Group 1: Cycles 0 (1..3), 1 (4..6), 2 (7..9)
        edges.extend_from_slice(&[(1, 2), (2, 3), (3, 1)]);
        edges.extend_from_slice(&[(4, 5), (5, 6), (6, 4)]);
        edges.extend_from_slice(&[(7, 8), (8, 9), (9, 7)]);
        edges.extend_from_slice(&[(2, 4), (5, 7), (8, 1)]);

        // Group 2: Cycles 3 (10..12), 4 (13..15), 5 (16..18)
        edges.extend_from_slice(&[(10, 11), (11, 12), (12, 10)]);
        edges.extend_from_slice(&[(13, 14), (14, 15), (15, 13)]);
        edges.extend_from_slice(&[(16, 17), (17, 18), (18, 16)]);
        edges.extend_from_slice(&[(11, 13), (14, 16), (17, 10)]);

        // Group 3: Cycles 6 (19..21), 7 (22..24), 8 (25..27)
        edges.extend_from_slice(&[(19, 20), (20, 21), (21, 19)]);
        edges.extend_from_slice(&[(22, 23), (23, 24), (24, 22)]);
        edges.extend_from_slice(&[(25, 26), (26, 27), (27, 25)]);
        edges.extend_from_slice(&[(20, 22), (23, 25), (26, 19)]);

        // Inter-group cross edges (connecting adjacent nodes in the merged cycles):
        edges.extend_from_slice(&[(3, 11), (13, 20), (22, 2)]);

        let g = build_test_graph(&edges);
        let contractor = empty_contractor();
        let hub_registry = empty_hub_registry();

        let cycles = vec![
            vec![1, 2, 3],
            vec![4, 5, 6],
            vec![7, 8, 9],
            vec![10, 11, 12],
            vec![13, 14, 15],
            vec![16, 17, 18],
            vec![19, 20, 21],
            vec![22, 23, 24],
            vec![25, 26, 27],
        ];

        let patched = ChainedLKSolver::patch_cycles_via_chained_lk(&cycles, &g, &contractor, &hub_registry, 6);
        assert_eq!(patched.len(), 1, "Iterative Chained LK should converge all 9 cycles to 1");
        assert_eq!(patched[0].len(), 27, "Final tour must contain all 27 vertices");
        assert!(is_valid_cycle(&patched[0], &g), "Final tour must be valid in G");
    }

    #[test]
    fn test_chained_lk_degree2_safety() {
        // In the 4-cycle loop, if the necessary break edge (1, 2) in Cycle 0 is protected by contractor,
        // Chained LK must NOT break it and must leave cycles unchanged.
        let edges = vec![
            (1, 2), (2, 3), (3, 4), (4, 1),
            (5, 6), (6, 7), (7, 8), (8, 5),
            (9, 10), (10, 11), (11, 12), (12, 9),
            (13, 14), (14, 15), (15, 16), (16, 13),
            (2, 5), (6, 9), (10, 13), (14, 1),
        ];

        let g = build_test_graph(&edges);
        let mut contractor = empty_contractor();
        let hub_registry = empty_hub_registry();

        let cycles = vec![
            vec![1, 2, 3, 4],
            vec![5, 6, 7, 8],
            vec![9, 10, 11, 12],
            vec![13, 14, 15, 16],
        ];

        // Mark edge (1, 2) and (2, 1) as contracted in degree-2 chain
        contractor.chain_map.insert((1, 2), vec![100]);
        contractor.chain_map.insert((2, 1), vec![100]);

        let merged_opt = ChainedLKSolver::search_alternating_chain(&cycles, &g, &contractor, &hub_registry, 4);
        assert!(merged_opt.is_none(), "Must not break contracted degree-2 edge");

        let patched = ChainedLKSolver::patch_cycles_via_chained_lk(&cycles, &g, &contractor, &hub_registry, 4);
        assert_eq!(patched.len(), 4, "Must preserve all 4 cycles without invalid cuts");

        // When restriction is lifted, it merges successfully
        let clean_contractor = empty_contractor();
        let patched_clean = ChainedLKSolver::patch_cycles_via_chained_lk(&cycles, &g, &clean_contractor, &hub_registry, 4);
        assert_eq!(patched_clean.len(), 1);
        assert_eq!(patched_clean[0].len(), 16);
    }

    #[test]
    fn bounded_chained_lk_stops_before_search_when_deadline_expired() {
        let g = build_test_graph(&[
            (1, 2), (2, 3), (3, 1),
            (4, 5), (5, 6), (6, 4),
            (7, 8), (8, 9), (9, 7),
        ]);
        let cycles = vec![vec![1, 2, 3], vec![4, 5, 6], vec![7, 8, 9]];
        let contractor = empty_contractor();
        let hubs = empty_hub_registry();
        let expired = Instant::now()
            .checked_sub(Duration::from_secs(1))
            .expect("Instant must support a one-second look-back");

        let result = ChainedLKSolver::patch_cycles_via_chained_lk_bounded(
            &cycles,
            &g,
            &contractor,
            &hubs,
            6,
            32,
            expired,
        );

        assert!(result.budget_exhausted);
        assert_eq!(result.iterations, 0);
        assert_eq!(result.cycles, cycles);
        assert!(!result.round_limit_reached);
    }
}
