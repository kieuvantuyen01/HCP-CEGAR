use crate::graph::Graph;
use std::collections::{BTreeMap, HashMap, HashSet};

pub struct Degree2Contractor {
    pub chain_map: HashMap<(i32, i32), Vec<i32>>,
    pub original_vertices_count: usize,
    pub contracted_vertices_count: usize,
    pub is_direct_cycle: Option<Vec<i32>>,
    pub is_infeasible: bool,
}

impl Degree2Contractor {
    /// Creates a no-op contractor for controlled ablation experiments.
    pub fn identity(g: &Graph) -> Degree2Contractor {
        let total_v = g.adjacency_list.len();
        Degree2Contractor {
            chain_map: HashMap::new(),
            original_vertices_count: total_v,
            contracted_vertices_count: total_v,
            is_direct_cycle: None,
            is_infeasible: false,
        }
    }

    pub fn contract(g: &Graph) -> (Graph, Degree2Contractor) {
        let total_v = g.adjacency_list.len();
        let mut adj: HashMap<i32, HashSet<i32>> = HashMap::new();
        for (&u, neighbors) in &g.adjacency_list {
            adj.insert(u, neighbors.iter().cloned().collect());
        }

        // Identify degree-2 vertices
        let deg2_vertices: HashSet<i32> = adj
            .iter()
            .filter(|(_, neighbors)| neighbors.len() == 2)
            .map(|(&u, _)| u)
            .collect();

        // Check for isolated 2-regular cycle
        if deg2_vertices.len() == total_v && total_v >= 3 {
            // Find full cycle
            let mut cycle = Vec::new();
            let start = *deg2_vertices.iter().next().unwrap();
            let mut curr = start;
            let mut prev = -1;
            let mut visited = HashSet::new();

            while !visited.contains(&curr) {
                visited.insert(curr);
                cycle.push(curr);
                let neighbors: Vec<i32> = adj[&curr].iter().cloned().collect();
                let next = if neighbors[0] == prev {
                    neighbors[1]
                } else {
                    neighbors[0]
                };
                prev = curr;
                curr = next;
            }

            if cycle.len() == total_v {
                return (
                    g.clone(),
                    Degree2Contractor {
                        chain_map: HashMap::new(),
                        original_vertices_count: total_v,
                        contracted_vertices_count: total_v,
                        is_direct_cycle: Some(cycle),
                        is_infeasible: false,
                    },
                );
            } else {
                return (
                    g.clone(),
                    Degree2Contractor {
                        chain_map: HashMap::new(),
                        original_vertices_count: total_v,
                        contracted_vertices_count: total_v,
                        is_direct_cycle: None,
                        is_infeasible: true,
                    },
                );
            }
        }

        let mut chain_map: HashMap<(i32, i32), Vec<i32>> = HashMap::new();
        let mut visited_deg2 = HashSet::new();
        let mut edge_chains: HashMap<(i32, i32), Vec<Vec<i32>>> = HashMap::new();

        for &v in &deg2_vertices {
            if visited_deg2.contains(&v) {
                continue;
            }

            let neighbors: Vec<i32> = adj[&v].iter().cloned().collect();
            if neighbors.len() != 2 {
                continue;
            }

            // Trace path in direction 1 (through neighbors[0])
            let mut path_left = Vec::new();
            let mut curr = v;
            let mut prev = neighbors[1];

            while deg2_vertices.contains(&curr) {
                if visited_deg2.contains(&curr) && curr != v {
                    // Loop of degree-2 vertices disconnected from non-degree-2 vertices
                    return (
                        g.clone(),
                        Degree2Contractor {
                            chain_map: HashMap::new(),
                            original_vertices_count: total_v,
                            contracted_vertices_count: total_v,
                            is_direct_cycle: None,
                            is_infeasible: true,
                        },
                    );
                }
                visited_deg2.insert(curr);
                path_left.push(curr);
                let nbrs: Vec<i32> = adj[&curr].iter().cloned().collect();
                let next = if nbrs[0] == prev { nbrs[1] } else { nbrs[0] };
                prev = curr;
                curr = next;
            }
            let end_u = curr; // non-degree-2 vertex

            // Trace path in direction 2 (through neighbors[1])
            let mut path_right = Vec::new();
            curr = neighbors[1];
            prev = v;
            while deg2_vertices.contains(&curr) {
                if visited_deg2.contains(&curr) {
                    return (
                        g.clone(),
                        Degree2Contractor {
                            chain_map: HashMap::new(),
                            original_vertices_count: total_v,
                            contracted_vertices_count: total_v,
                            is_direct_cycle: None,
                            is_infeasible: true,
                        },
                    );
                }
                visited_deg2.insert(curr);
                path_right.push(curr);
                let nbrs: Vec<i32> = adj[&curr].iter().cloned().collect();
                let next = if nbrs[0] == prev { nbrs[1] } else { nbrs[0] };
                prev = curr;
                curr = next;
            }
            let end_w = curr; // non-degree-2 vertex

            if end_u == end_w {
                // Cycle of degree 2 attached to a single non-degree-2 vertex (cut vertex)
                return (
                    g.clone(),
                    Degree2Contractor {
                        chain_map: HashMap::new(),
                        original_vertices_count: total_v,
                        contracted_vertices_count: total_v,
                        is_direct_cycle: None,
                        is_infeasible: true,
                    },
                );
            }

            // Form complete ordered intermediate path from end_u to end_w
            // path_left was built starting at v moving towards end_u: [v, left_1, ..., left_k]
            // So from end_u towards end_w: reverse(path_left) ++ path_right
            path_left.reverse();
            let mut full_path = path_left;
            full_path.extend(path_right);

            let key = if end_u < end_w {
                (end_u, end_w)
            } else {
                (end_w, end_u)
            };

            let ordered_for_key = if end_u < end_w {
                full_path
            } else {
                let mut rev = full_path;
                rev.reverse();
                rev
            };

            edge_chains.entry(key).or_insert_with(Vec::new).push(ordered_for_key);
        }

        // Validate parallel chains and build final chain_map
        let mut contracted_adj: HashMap<i32, HashSet<i32>> = HashMap::new();
        for (&u, neighbors) in &adj {
            if !deg2_vertices.contains(&u) {
                contracted_adj.insert(u, HashSet::new());
                for &v in neighbors {
                    if !deg2_vertices.contains(&v) {
                        contracted_adj.get_mut(&u).unwrap().insert(v);
                    }
                }
            }
        }

        for (&(u, w), chains) in &edge_chains {
            if chains.len() > 1 {
                let total_chain_verts: usize = chains.iter().map(|c| c.len()).sum();
                if chains.len() > 2 || total_chain_verts + 2 < total_v {
                    return (
                        g.clone(),
                        Degree2Contractor {
                            chain_map: HashMap::new(),
                            original_vertices_count: total_v,
                            contracted_vertices_count: total_v,
                            is_direct_cycle: None,
                            is_infeasible: true,
                        },
                    );
                } else if chains.len() == 2 && total_chain_verts + 2 == total_v {
                    let mut cycle = Vec::new();
                    cycle.push(u);
                    for &v in &chains[0] {
                        cycle.push(v);
                    }
                    cycle.push(w);
                    for &v in chains[1].iter().rev() {
                        cycle.push(v);
                    }
                    return (
                        g.clone(),
                        Degree2Contractor {
                            chain_map: HashMap::new(),
                            original_vertices_count: total_v,
                            contracted_vertices_count: total_v,
                            is_direct_cycle: Some(cycle),
                            is_infeasible: false,
                        },
                    );
                }
            }

            // Store bidirectional mappings
            let fwd_chain = chains[0].clone();
            let mut rev_chain = fwd_chain.clone();
            rev_chain.reverse();

            chain_map.insert((u, w), fwd_chain);
            chain_map.insert((w, u), rev_chain);

            // Add contracted virtual edge
            contracted_adj.entry(u).or_default().insert(w);
            contracted_adj.entry(w).or_default().insert(u);
        }

        // Build contracted Graph struct
        let mut final_adj = HashMap::new();
        let mut final_btree_adj = BTreeMap::new();
        let mut final_arcs = Vec::new();

        for (&u, neighbors) in &contracted_adj {
            let mut nbr_vec: Vec<i32> = neighbors.iter().cloned().collect();
            nbr_vec.sort();
            final_adj.insert(u, nbr_vec.clone());
            final_btree_adj.insert(u, nbr_vec.clone());
            for &v in &nbr_vec {
                final_arcs.push((u, v));
            }
        }

        let contracted_v = final_adj.len();
        let cg = Graph {
            adjacency_list: final_adj,
            adjacency_list_btree: final_btree_adj,
            arcs: final_arcs,
        };

        (
            cg,
            Degree2Contractor {
                chain_map,
                original_vertices_count: total_v,
                contracted_vertices_count: contracted_v,
                is_direct_cycle: None,
                is_infeasible: false,
            },
        )
    }

    pub fn uncontract_cycle(&self, contracted_cycle: &[i32]) -> Vec<i32> {
        let mut full_cycle = Vec::new();
        let len = contracted_cycle.len();
        if len == 0 {
            return full_cycle;
        }

        for i in 0..len {
            let u = contracted_cycle[i];
            let v = contracted_cycle[(i + 1) % len];
            full_cycle.push(u);
            if let Some(intermediates) = self.chain_map.get(&(u, v)) {
                for &inter in intermediates {
                    full_cycle.push(inter);
                }
            }
        }

        full_cycle
    }

    pub fn uncontract_path(&self, contracted_path: &[i32]) -> Vec<i32> {
        let mut full_path = Vec::new();
        let len = contracted_path.len();
        if len == 0 {
            return full_path;
        }

        for i in 0..len {
            let u = contracted_path[i];
            full_path.push(u);
            if i + 1 < len {
                let v = contracted_path[i + 1];
                if let Some(intermediates) = self.chain_map.get(&(u, v)) {
                    for &inter in intermediates {
                        full_path.push(inter);
                    }
                }
            }
        }

        full_path
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::Graph;
    use std::collections::HashMap;

    fn build_test_graph(edges: &[(i32, i32)], total_v: usize) -> Graph {
        let mut adj = HashMap::new();
        for i in 1..=total_v as i32 {
            adj.insert(i, Vec::new());
        }
        let mut arcs = Vec::new();
        for &(u, v) in edges {
            adj.get_mut(&u).unwrap().push(v);
            adj.get_mut(&v).unwrap().push(u);
            arcs.push((u, v));
            arcs.push((v, u));
        }
        let mut btree_adj = std::collections::BTreeMap::new();
        for (&k, v) in &adj {
            btree_adj.insert(k, v.clone());
        }
        Graph {
            adjacency_list: adj,
            adjacency_list_btree: btree_adj,
            arcs,
        }
    }

    #[test]
    fn test_contract_single_degree2_chain() {
        // Graph: 1 - 2 - 3 (chain of length 1) with endpoints 1 and 3 connected to 4 and 5
        // 4 and 5 connected to each other so deg(4)=3, deg(5)=3
        let edges = vec![
            (1, 2), (2, 3),
            (1, 4), (3, 4),
            (1, 5), (3, 5),
            (4, 5),
        ];
        let g = build_test_graph(&edges, 5);
        let (cg, contractor) = Degree2Contractor::contract(&g);
        assert!(!contractor.is_infeasible);
        assert_eq!(contractor.original_vertices_count, 5);
        assert_eq!(contractor.contracted_vertices_count, 4);
        assert!(cg.adjacency_list.get(&1).unwrap().contains(&3));
    }

    #[test]
    fn test_contract_multi_step_chain_and_uncontract() {
        // 4-cycle with intermediate chain: 1 - 5 - 6 - 2, 2 - 3, 3 - 4, 4 - 1
        // Vertices: 1, 2, 3, 4 (deg >= 3) and 5, 6 (deg=2)
        let edges = vec![
            (1, 5), (5, 6), (6, 2),
            (2, 3), (3, 4), (4, 1),
            (1, 3), (2, 4),
        ];
        let g = build_test_graph(&edges, 6);
        let (_cg, contractor) = Degree2Contractor::contract(&g);
        assert_eq!(contractor.original_vertices_count, 6);
        assert_eq!(contractor.contracted_vertices_count, 4);
        assert!(contractor.chain_map.contains_key(&(1, 2)) || contractor.chain_map.contains_key(&(2, 1)));

        // Contracted cycle: [1, 2, 3, 4]
        let contracted_cycle = vec![1, 2, 3, 4];
        let full_cycle = contractor.uncontract_cycle(&contracted_cycle);
        assert_eq!(full_cycle.len(), 6);
        assert_eq!(full_cycle, vec![1, 5, 6, 2, 3, 4]);
    }

    #[test]
    fn test_contract_pure_cycle() {
        // 4-cycle: 1 - 2 - 3 - 4 - 1 (all deg=2)
        let edges = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
        let g = build_test_graph(&edges, 4);
        let (_, contractor) = Degree2Contractor::contract(&g);
        assert!(contractor.is_direct_cycle.is_some());
        let cycle = contractor.is_direct_cycle.unwrap();
        assert_eq!(cycle.len(), 4);
    }

    #[test]
    fn test_contract_infeasible_parallel_chains() {
        // 1 - 3 - 2, 1 - 4 - 2, 1 - 5 - 2 (3 parallel chains between 1 and 2)
        let edges = vec![(1, 3), (3, 2), (1, 4), (4, 2), (1, 5), (2, 5)];
        let g = build_test_graph(&edges, 5);
        let (_, contractor) = Degree2Contractor::contract(&g);
        assert!(contractor.is_infeasible);
    }
}
