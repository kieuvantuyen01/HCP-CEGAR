use crate::contraction::Degree2Contractor;
use crate::graph::Graph;
use crate::hub_registry::HubRegistry;
use std::collections::HashMap;

/// Global maximum matching patcher for disjoint simultaneous 2-opt cycle merges.
pub struct MatchingPatcher;

impl MatchingPatcher {
    /// Finds a 2-opt merge whose two replacement edges both occur in `guide`.
    ///
    /// This is used by population recombination: `guide` is the edge set of a
    /// previous cycle cover, while `g` is the original graph.  The guide only
    /// orders/restricts the search; every returned cycle is validated in `g`.
    /// Looking up the at-most-two guide neighbours of each endpoint avoids the
    /// quadratic all-edge-pairs scan used by the unrestricted patcher.
    pub fn try_find_guided_2opt_merge(
        c1: &[i32],
        c2: &[i32],
        guide: &Graph,
        g: &Graph,
        contractor: &Degree2Contractor,
    ) -> Option<Vec<i32>> {
        let k1 = c1.len();
        let k2 = c2.len();
        if k1 < 3 || k2 < 3 {
            return None;
        }

        let positions_c2: HashMap<i32, usize> = c2
            .iter()
            .enumerate()
            .map(|(position, &vertex)| (vertex, position))
            .collect();

        for i in 0..k1 {
            let u = c1[i];
            let u_next = c1[(i + 1) % k1];
            if !is_safe_to_break(u, u_next, contractor) {
                continue;
            }

            let Some(u_guides) = guide.adjacency_list.get(&u) else {
                continue;
            };
            let Some(u_next_guides) = guide.adjacency_list.get(&u_next) else {
                continue;
            };

            for &w in u_guides {
                let Some(&w_position) = positions_c2.get(&w) else {
                    continue;
                };
                for &w_next in u_next_guides {
                    let Some(&w_next_position) = positions_c2.get(&w_next) else {
                        continue;
                    };

                    // Orientation 1: u--w and u_next--w_next, where w_next
                    // follows w in c2.
                    if w_next_position == (w_position + 1) % k2
                        && is_safe_to_break(w, w_next, contractor)
                    {
                        let merged = build_2opt_merge(c1, c2, i, w_position, false);
                        if is_valid_cycle(&merged, g) {
                            return Some(merged);
                        }
                    }

                    // Orientation 2: u--w and u_next--w_next, where w follows
                    // w_next in c2.  Here w_next is c2[j] and w is c2[j+1].
                    if w_position == (w_next_position + 1) % k2
                        && is_safe_to_break(w_next, w, contractor)
                    {
                        let merged = build_2opt_merge(c1, c2, i, w_next_position, true);
                        if is_valid_cycle(&merged, g) {
                            return Some(merged);
                        }
                    }
                }
            }
        }

        None
    }

    /// Attempts to find a valid 2-opt reconnection between subcycle `c1` and `c2`.
    ///
    /// Evaluates all pairs of break edges `(c1[i], c1[i+1])` and `(c2[j], c2[j+1])`,
    /// enforcing degree-2 contraction safety on both edges. Checks both reconnection
    /// orientations and verifies full edge adjacency in `g`.
    /// Returns `Some(merged_cycle)` on the first valid reconnection found, or `None`.
    pub fn try_find_2opt_merge(
        c1: &[i32],
        c2: &[i32],
        g: &Graph,
        contractor: &Degree2Contractor,
    ) -> Option<Vec<i32>> {
        let k1 = c1.len();
        let k2 = c2.len();
        if k1 < 3 || k2 < 3 {
            return None;
        }

        for i in 0..k1 {
            let u_i = c1[i];
            let u_ip1 = c1[(i + 1) % k1];

            if !is_safe_to_break(u_i, u_ip1, contractor) {
                continue;
            }

            let Some(adj_ui) = g.adjacency_list.get(&u_i) else {
                continue;
            };
            let Some(adj_uip1) = g.adjacency_list.get(&u_ip1) else {
                continue;
            };

            for j in 0..k2 {
                let w_j = c2[j];
                let w_jp1 = c2[(j + 1) % k2];

                if !is_safe_to_break(w_j, w_jp1, contractor) {
                    continue;
                }

                // Orientation 1: u_i <-> w_j and u_ip1 <-> w_jp1
                if adj_ui.contains(&w_j) && adj_uip1.contains(&w_jp1) {
                    let merged = build_2opt_merge(c1, c2, i, j, false);
                    if is_valid_cycle(&merged, g) {
                        return Some(merged);
                    }
                }

                // Orientation 2: u_i <-> w_jp1 and u_ip1 <-> w_j
                if adj_ui.contains(&w_jp1) && adj_uip1.contains(&w_j) {
                    let merged = build_2opt_merge(c1, c2, i, j, true);
                    if is_valid_cycle(&merged, g) {
                        return Some(merged);
                    }
                }
            }
        }

        None
    }

    /// Evaluates all mergeable candidate pairs among `cycles`, assigns weights $W(i, j) = |C_i| + |C_j|$,
    /// sorts by descending weight, and greedily extracts a maximum-weight disjoint matching.
    pub fn find_max_weight_matching(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        _hub_registry: &HubRegistry,
    ) -> Vec<(usize, usize, Vec<i32>)> {
        if cycles.len() < 2 {
            return Vec::new();
        }

        struct Candidate {
            i: usize,
            j: usize,
            weight: usize,
            merged: Vec<i32>,
        }

        let mut candidates = Vec::new();
        for i in 0..cycles.len() {
            for j in (i + 1)..cycles.len() {
                if let Some(merged) = Self::try_find_2opt_merge(&cycles[i], &cycles[j], g, contractor) {
                    let weight = cycles[i].len() + cycles[j].len();
                    candidates.push(Candidate { i, j, weight, merged });
                }
            }
        }

        // Sort candidates by descending weight (favoring larger subcycle aggregations)
        candidates.sort_by(|a, b| b.weight.cmp(&a.weight));

        let mut used = vec![false; cycles.len()];
        let mut matching = Vec::new();

        for cand in candidates {
            if !used[cand.i] && !used[cand.j] {
                used[cand.i] = true;
                used[cand.j] = true;
                matching.push((cand.i, cand.j, cand.merged));
            }
        }

        matching
    }

    /// Iteratively applies Maximum Matching Global Patching across all subcycles.
    ///
    /// In each round:
    /// 1. Finds a maximal disjoint matching of mergeable subcycle pairs.
    /// 2. Performs batch merges for all matched pairs simultaneously.
    /// 3. Retains untouched subcycles.
    /// 4. Repeats until convergence or until a single cycle is formed.
    pub fn patch_cycles_via_matching(
        cycles: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
    ) -> Vec<Vec<i32>> {
        if cycles.len() <= 1 {
            return cycles.to_vec();
        }

        let mut current_cycles = cycles.to_vec();
        let max_iterations = current_cycles.len() * 2;

        for _ in 0..max_iterations {
            if current_cycles.len() <= 1 {
                break;
            }

            let matching = Self::find_max_weight_matching(&current_cycles, g, contractor, hub_registry);
            if matching.is_empty() {
                break;
            }

            let mut matched = vec![false; current_cycles.len()];
            let mut next_cycles = Vec::with_capacity(current_cycles.len() - matching.len());

            for (i, j, merged) in matching {
                matched[i] = true;
                matched[j] = true;
                next_cycles.push(merged);
            }

            for (idx, c) in current_cycles.into_iter().enumerate() {
                if !matched[idx] {
                    next_cycles.push(c);
                }
            }

            current_cycles = next_cycles;
        }

        current_cycles
    }
}

fn build_2opt_merge(
    c1: &[i32],
    c2: &[i32],
    c1_break: usize,
    c2_break: usize,
    orientation_two: bool,
) -> Vec<i32> {
    let mut merged = Vec::with_capacity(c1.len() + c2.len());
    merged.extend_from_slice(&c1[0..=c1_break]);
    if orientation_two {
        for offset in 0..c2.len() {
            merged.push(c2[(c2_break + 1 + offset) % c2.len()]);
        }
    } else {
        for offset in 0..c2.len() {
            merged.push(c2[(c2_break + c2.len() - offset) % c2.len()]);
        }
    }
    if c1_break + 1 < c1.len() {
        merged.extend_from_slice(&c1[c1_break + 1..]);
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
    use std::collections::{HashMap, HashSet};

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
    fn test_matching_patcher_disjoint_pairs() {
        // 4 subcycles:
        // Cycle 0: 1 - 2 - 3 - 1
        // Cycle 1: 4 - 5 - 6 - 4
        // Cross edges (0, 1): (1, 4) and (2, 5) -> merges (0, 1) by breaking (1, 2) and (4, 5)
        // Cycle 2: 7 - 8 - 9 - 7
        // Cycle 3: 10 - 11 - 12 - 10
        // Cross edges (2, 3): (7, 10) and (8, 11) -> merges (2, 3) by breaking (7, 8) and (10, 11)
        // No cross edges between {1..6} and {7..12}.
        let edges = vec![
            // Cycle 0
            (1, 2), (2, 3), (3, 1),
            // Cycle 1
            (4, 5), (5, 6), (6, 4),
            // Cross edges 0 <-> 1
            (1, 4), (2, 5),
            // Cycle 2
            (7, 8), (8, 9), (9, 7),
            // Cycle 3
            (10, 11), (11, 12), (12, 10),
            // Cross edges 2 <-> 3
            (7, 10), (8, 11),
        ];

        let g = build_test_graph(&edges);
        let contractor = empty_contractor();
        let hub_registry = empty_hub_registry();

        let cycles = vec![
            vec![1, 2, 3],
            vec![4, 5, 6],
            vec![7, 8, 9],
            vec![10, 11, 12],
        ];

        let matching = MatchingPatcher::find_max_weight_matching(&cycles, &g, &contractor, &hub_registry);
        assert_eq!(matching.len(), 2, "Should find 2 disjoint pairs in 1 matching pass");

        let patched = MatchingPatcher::patch_cycles_via_matching(&cycles, &g, &contractor, &hub_registry);
        assert_eq!(patched.len(), 2, "Should merge 4 subcycles into 2 disjoint cycles");
        assert_eq!(patched[0].len(), 6);
        assert_eq!(patched[1].len(), 6);
        assert!(is_valid_cycle(&patched[0], &g));
        assert!(is_valid_cycle(&patched[1], &g));

        let all_verts: HashSet<i32> = patched.iter().flatten().cloned().collect();
        let expected: HashSet<i32> = (1..=12).collect();
        assert_eq!(all_verts, expected);
    }

    #[test]
    fn test_matching_patcher_full_convergence() {
        // 4 subcycles that merge in 2 iterations into 1 single Hamiltonian cycle:
        // Iteration 1: (0, 1) -> 6-cycle, (2, 3) -> 6-cycle
        // Iteration 2: 6-cycle and 6-cycle -> 12-cycle
        let edges = vec![
            // Cycle 0
            (1, 2), (2, 3), (3, 1),
            // Cycle 1
            (4, 5), (5, 6), (6, 4),
            // Cross edges 0 <-> 1 (breaks (1, 2) in C0, (4, 5) in C1)
            (1, 4), (2, 5),
            // Cycle 2
            (7, 8), (8, 9), (9, 7),
            // Cycle 3
            (10, 11), (11, 12), (12, 10),
            // Cross edges 2 <-> 3 (breaks (7, 8) in C2, (10, 11) in C3)
            (7, 10), (8, 11),
            // Cross edges between (C0+C1) and (C2+C3)
            // In C0+C1, edge (3, 1) remains. In C2+C3, edge (9, 7) remains.
            // Breaking (3, 1) and (9, 7) via cross edges (3, 9) and (1, 7)
            (3, 9), (1, 7),
        ];

        let g = build_test_graph(&edges);
        let contractor = empty_contractor();
        let hub_registry = empty_hub_registry();

        let cycles = vec![
            vec![1, 2, 3],
            vec![4, 5, 6],
            vec![7, 8, 9],
            vec![10, 11, 12],
        ];

        let patched = MatchingPatcher::patch_cycles_via_matching(&cycles, &g, &contractor, &hub_registry);
        assert_eq!(patched.len(), 1, "Should iteratively merge all 4 subcycles into 1 full cycle");
        assert_eq!(patched[0].len(), 12, "Full cycle should contain all 12 vertices");
        assert!(is_valid_cycle(&patched[0], &g), "Merged cycle must be valid in G");

        let all_verts: HashSet<i32> = patched[0].iter().cloned().collect();
        let expected: HashSet<i32> = (1..=12).collect();
        assert_eq!(all_verts, expected);
    }

    #[test]
    fn test_matching_patcher_degree2_safety() {
        // Cycle 0: 1 - 2 - 3 - 1
        // Cycle 1: 4 - 5 - 6 - 4
        // Cross edges: (1, 4) and (2, 5) which requires breaking (1, 2) in C0 and (4, 5) in C1.
        // If (1, 2) is a contracted degree-2 chain edge, it must NOT be severed.
        let edges = vec![
            (1, 2), (2, 3), (3, 1),
            (4, 5), (5, 6), (6, 4),
            (1, 4), (2, 5),
        ];

        let g = build_test_graph(&edges);
        let mut contractor = empty_contractor();
        contractor.chain_map.insert((1, 2), vec![1, 99, 2]);
        let hub_registry = empty_hub_registry();

        let cycles = vec![vec![1, 2, 3], vec![4, 5, 6]];

        // try_find_2opt_merge should return None because the only candidate break edge (1, 2) is protected
        let merge_res = MatchingPatcher::try_find_2opt_merge(&cycles[0], &cycles[1], &g, &contractor);
        assert!(merge_res.is_none(), "Must not break contracted degree-2 edge (1, 2)");

        let patched = MatchingPatcher::patch_cycles_via_matching(&cycles, &g, &contractor, &hub_registry);
        assert_eq!(patched.len(), 2, "Should NOT merge cycles when required break edge is in chain_map");
        assert_eq!(patched[0].len(), 3);
        assert_eq!(patched[1].len(), 3);
    }
}
