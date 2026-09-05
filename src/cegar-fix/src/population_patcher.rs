use crate::chained_lk::ChainedLKSolver;
use crate::contraction::Degree2Contractor;
use crate::graph::Graph;
use crate::hub_registry::HubRegistry;
use crate::matching_patcher::MatchingPatcher;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::time::Instant;

type Edge = (i32, i32);

// Recombination alternates two convergent local searches. Absolute caps keep a
// single SAT model from monopolising the CEGAR budget on unusually large covers.
const MAX_PARENT_ALTERNATION_ROUNDS: usize = 32;
const MAX_GUIDED_MATCHING_ROUNDS: usize = 64;
const MAX_CHAINED_LK_ROUNDS: usize = 32;
const MAX_RETRY_GAP: usize = 63;

#[derive(Clone, Debug)]
struct PopulationEntry {
    cycles: Vec<Vec<i32>>,
    edges: BTreeSet<Edge>,
    generation: u64,
}

/// Observable result of one population-guided repair attempt.
#[derive(Clone, Debug)]
pub struct PopulationPatchResult {
    pub cycles: Vec<Vec<i32>>,
    pub parents_tried: usize,
    pub improvements: usize,
    pub population_size_before: usize,
    pub population_size_after: usize,
    pub budget_exhausted: bool,
    pub outer_rounds: usize,
    pub guided_rounds: usize,
    pub chained_lk_rounds: usize,
    pub round_limit_hits: usize,
    pub cooldown_skipped: bool,
}

#[derive(Clone, Debug)]
struct RecombinationResult {
    cycles: Vec<Vec<i32>>,
    budget_exhausted: bool,
    outer_rounds: usize,
    guided_rounds: usize,
    chained_lk_rounds: usize,
    round_limit_hits: usize,
}

#[derive(Clone, Debug)]
struct GuidedMatchingResult {
    cycles: Vec<Vec<i32>>,
    budget_exhausted: bool,
    rounds: usize,
    round_limit_reached: bool,
}

/// Small deterministic population of earlier SAT cycle covers.
///
/// The best cover (fewest subcycles) is retained as an elite and the remaining
/// slots keep recent, edge-distinct covers.  Recombination never invents an
/// edge: it starts from the current cover and reconnects it using edges from a
/// selected parent.  Every accepted offspring is checked against the original
/// graph before it can be used by the CEGAR loop.
pub struct PopulationPatcher {
    capacity: usize,
    max_parents: usize,
    entries: Vec<PopulationEntry>,
    next_generation: u64,
    failed_attempt_streak: usize,
    calls_since_attempt: usize,
}

impl PopulationPatcher {
    pub fn new(capacity: usize, max_parents: usize) -> Self {
        Self {
            capacity: capacity.max(2),
            max_parents: max_parents.max(1),
            entries: Vec::new(),
            next_generation: 0,
            failed_attempt_streak: 0,
            calls_since_attempt: 0,
        }
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.entries.len()
    }

    /// Try edge-assembly recombination with the most relevant previous covers,
    /// then retain the current cover and any strictly better offspring.
    pub fn patch_and_observe(
        &mut self,
        current: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
    ) -> PopulationPatchResult {
        self.patch_and_observe_with_deadline(current, g, contractor, hub_registry, None)
    }

    /// Deadline-aware entry point used by CEGAR.
    pub fn patch_and_observe_until(
        &mut self,
        current: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        deadline: Instant,
    ) -> PopulationPatchResult {
        self.patch_and_observe_with_deadline(
            current,
            g,
            contractor,
            hub_registry,
            Some(deadline),
        )
    }

    fn patch_and_observe_with_deadline(
        &mut self,
        current: &[Vec<i32>],
        g: &Graph,
        contractor: &Degree2Contractor,
        hub_registry: &HubRegistry,
        deadline: Option<Instant>,
    ) -> PopulationPatchResult {
        let population_size_before = self.entries.len();
        // Check the global budget before validation or cooldown handling.  In
        // particular, a skipped recombination must not hide an already expired
        // deadline and let the rest of the CEGAR iteration run past its cap.
        if deadline_reached(deadline) {
            return PopulationPatchResult {
                cycles: current.to_vec(),
                parents_tried: 0,
                improvements: 0,
                population_size_before,
                population_size_after: population_size_before,
                budget_exhausted: true,
                outer_rounds: 0,
                guided_rounds: 0,
                chained_lk_rounds: 0,
                round_limit_hits: 0,
                cooldown_skipped: false,
            };
        }
        if !is_valid_cycle_cover(current, g) {
            return PopulationPatchResult {
                cycles: current.to_vec(),
                parents_tried: 0,
                improvements: 0,
                population_size_before,
                population_size_after: population_size_before,
                budget_exhausted: false,
                outer_rounds: 0,
                guided_rounds: 0,
                chained_lk_rounds: 0,
                round_limit_hits: 0,
                cooldown_skipped: false,
            };
        }
        let retry_gap = retry_gap(self.failed_attempt_streak);
        if self.calls_since_attempt < retry_gap {
            self.calls_since_attempt += 1;
            self.observe(current);
            return PopulationPatchResult {
                cycles: current.to_vec(),
                parents_tried: 0,
                improvements: 0,
                population_size_before,
                population_size_after: self.entries.len(),
                budget_exhausted: false,
                outer_rounds: 0,
                guided_rounds: 0,
                chained_lk_rounds: 0,
                round_limit_hits: 0,
                cooldown_skipped: true,
            };
        }
        self.calls_since_attempt = 0;
        let parent_indices = self.select_parents(current);
        let parents: Vec<Vec<Vec<i32>>> = parent_indices
            .iter()
            .map(|&index| self.entries[index].cycles.clone())
            .collect();

        let mut best = current.to_vec();
        let mut parents_tried = 0;
        let mut improvements = 0;
        let mut budget_exhausted = false;
        let mut outer_rounds = 0;
        let mut guided_rounds = 0;
        let mut chained_lk_rounds = 0;
        let mut round_limit_hits = 0;
        for parent in parents {
            if deadline_reached(deadline) {
                budget_exhausted = true;
                break;
            }
            parents_tried += 1;
            let recombined = recombine_with_parent(
                &best,
                &parent,
                g,
                contractor,
                hub_registry,
                deadline,
            );
            outer_rounds += recombined.outer_rounds;
            guided_rounds += recombined.guided_rounds;
            chained_lk_rounds += recombined.chained_lk_rounds;
            round_limit_hits += recombined.round_limit_hits;
            if recombined.cycles.len() < best.len()
                && is_valid_cycle_cover(&recombined.cycles, g)
            {
                best = recombined.cycles;
                improvements += 1;
                if best.len() == 1 {
                    break;
                }
            }
            if recombined.budget_exhausted {
                budget_exhausted = true;
                break;
            }
        }

        self.observe(current);
        if best.len() < current.len() {
            self.observe(&best);
        }
        if improvements > 0 {
            self.failed_attempt_streak = 0;
        } else if parents_tried > 0 && !budget_exhausted {
            self.failed_attempt_streak = self.failed_attempt_streak.saturating_add(1);
        }

        PopulationPatchResult {
            cycles: best,
            parents_tried,
            improvements,
            population_size_before,
            population_size_after: self.entries.len(),
            budget_exhausted,
            outer_rounds,
            guided_rounds,
            chained_lk_rounds,
            round_limit_hits,
            cooldown_skipped: false,
        }
    }

    fn observe(&mut self, cycles: &[Vec<i32>]) {
        let edges = cycle_edges(cycles);
        if self.entries.iter().any(|entry| entry.edges == edges) {
            return;
        }

        let entry = PopulationEntry {
            cycles: cycles.to_vec(),
            edges,
            generation: self.next_generation,
        };
        self.next_generation += 1;

        if self.entries.len() < self.capacity {
            self.entries.push(entry);
            return;
        }

        // Preserve one elite (fewest cycles; oldest wins a tie) and replace the
        // oldest non-elite.  This gives stable memory plus recent diversity.
        let elite_index = self
            .entries
            .iter()
            .enumerate()
            .min_by_key(|(_, existing)| (existing.cycles.len(), existing.generation))
            .map(|(index, _)| index)
            .unwrap_or(0);
        let replace_index = self
            .entries
            .iter()
            .enumerate()
            .filter(|(index, _)| *index != elite_index)
            .min_by_key(|(_, existing)| existing.generation)
            .map(|(index, _)| index)
            .unwrap_or(elite_index);
        self.entries[replace_index] = entry;
    }

    fn select_parents(&self, current: &[Vec<i32>]) -> Vec<usize> {
        if current.len() <= 1 {
            return Vec::new();
        }

        let mut vertex_cycle = HashMap::new();
        for (cycle_index, cycle) in current.iter().enumerate() {
            for &vertex in cycle {
                vertex_cycle.insert(vertex, cycle_index);
            }
        }
        let current_edges = cycle_edges(current);

        let mut ranked: Vec<(usize, usize, usize, usize, u64)> = self
            .entries
            .iter()
            .enumerate()
            .filter_map(|(index, entry)| {
                let crossing_edges = entry
                    .edges
                    .iter()
                    .filter(|&&(u, v)| {
                        matches!(
                            (vertex_cycle.get(&u), vertex_cycle.get(&v)),
                            (Some(left), Some(right)) if left != right
                        )
                    })
                    .count();
                if crossing_edges < 2 {
                    return None;
                }
                let edge_distance = current_edges.symmetric_difference(&entry.edges).count();
                Some((
                    index,
                    crossing_edges,
                    edge_distance,
                    entry.cycles.len(),
                    entry.generation,
                ))
            })
            .collect();

        ranked.sort_by(|left, right| {
            right
                .1
                .cmp(&left.1)
                .then_with(|| right.2.cmp(&left.2))
                .then_with(|| left.3.cmp(&right.3))
                .then_with(|| right.4.cmp(&left.4))
        });
        ranked
            .into_iter()
            .take(self.max_parents)
            .map(|rank| rank.0)
            .collect()
    }
}

fn recombine_with_parent(
    current: &[Vec<i32>],
    parent: &[Vec<i32>],
    g: &Graph,
    contractor: &Degree2Contractor,
    hub_registry: &HubRegistry,
    deadline: Option<Instant>,
) -> RecombinationResult {
    let parent_graph = graph_from_cycle_sets(&[parent]);
    let mut candidate = current.to_vec();
    let max_rounds = current
        .len()
        .saturating_mul(2)
        .max(1)
        .min(MAX_PARENT_ALTERNATION_ROUNDS);
    let mut outer_rounds = 0;
    let mut guided_rounds = 0;
    let mut chained_lk_rounds = 0;
    let mut round_limit_hits = 0;
    let mut budget_exhausted = false;
    let mut converged = false;

    for _ in 0..max_rounds {
        if deadline_reached(deadline) {
            budget_exhausted = true;
            break;
        }
        outer_rounds += 1;
        let before = candidate.len();
        let guided = guided_matching_rounds(
            &candidate,
            &parent_graph,
            g,
            contractor,
            deadline,
        );
        candidate = guided.cycles;
        guided_rounds += guided.rounds;
        round_limit_hits += usize::from(guided.round_limit_reached);
        if guided.budget_exhausted {
            budget_exhausted = true;
            break;
        }

        if candidate.len() >= 3 {
            let union_graph = graph_from_cycle_sets(&[&candidate, parent]);
            if let Some(limit) = deadline {
                let chained = ChainedLKSolver::patch_cycles_via_chained_lk_bounded(
                    &candidate,
                    &union_graph,
                    contractor,
                    hub_registry,
                    6,
                    MAX_CHAINED_LK_ROUNDS,
                    limit,
                );
                chained_lk_rounds += chained.iterations;
                round_limit_hits += usize::from(chained.round_limit_reached);
                if chained.cycles.len() < candidate.len()
                    && is_valid_cycle_cover(&chained.cycles, g)
                {
                    candidate = chained.cycles;
                }
                if chained.budget_exhausted {
                    budget_exhausted = true;
                    break;
                }
            } else {
                let chained = ChainedLKSolver::patch_cycles_via_chained_lk(
                    &candidate,
                    &union_graph,
                    contractor,
                    hub_registry,
                    6,
                );
                if chained.len() < candidate.len() && is_valid_cycle_cover(&chained, g) {
                    candidate = chained;
                }
            }
        }

        if candidate.len() >= before || !is_valid_cycle_cover(&candidate, g) {
            converged = true;
            break;
        }
        if candidate.len() == 1 {
            converged = true;
            break;
        }
    }

    if !budget_exhausted && !converged && outer_rounds == max_rounds {
        round_limit_hits += 1;
    }
    RecombinationResult {
        cycles: candidate,
        budget_exhausted,
        outer_rounds,
        guided_rounds,
        chained_lk_rounds,
        round_limit_hits,
    }
}

fn guided_matching_rounds(
    cycles: &[Vec<i32>],
    guide: &Graph,
    g: &Graph,
    contractor: &Degree2Contractor,
    deadline: Option<Instant>,
) -> GuidedMatchingResult {
    let mut current = cycles.to_vec();
    let max_rounds = current
        .len()
        .saturating_mul(2)
        .max(1)
        .min(MAX_GUIDED_MATCHING_ROUNDS);
    let mut rounds = 0;
    let mut budget_exhausted = false;
    let mut converged = false;

    for _ in 0..max_rounds {
        if deadline_reached(deadline) {
            budget_exhausted = true;
            break;
        }
        if current.len() <= 1 {
            converged = true;
            break;
        }
        rounds += 1;

        let mut vertex_cycle = HashMap::new();
        for (cycle_index, cycle) in current.iter().enumerate() {
            for &vertex in cycle {
                vertex_cycle.insert(vertex, cycle_index);
            }
        }

        let mut crossing_counts: BTreeMap<(usize, usize), usize> = BTreeMap::new();
        for &(u, v) in &guide.arcs {
            if u >= v {
                continue;
            }
            let (Some(&left), Some(&right)) = (vertex_cycle.get(&u), vertex_cycle.get(&v)) else {
                continue;
            };
            if left == right {
                continue;
            }
            let pair = if left < right { (left, right) } else { (right, left) };
            *crossing_counts.entry(pair).or_insert(0) += 1;
        }

        let mut pairs: Vec<(usize, usize, usize)> = crossing_counts
            .into_iter()
            .filter(|(_, count)| *count >= 2)
            .map(|((left, right), _)| (left, right, current[left].len() + current[right].len()))
            .collect();
        pairs.sort_by(|left, right| {
            right
                .2
                .cmp(&left.2)
                .then_with(|| left.0.cmp(&right.0))
                .then_with(|| left.1.cmp(&right.1))
        });

        let mut used = vec![false; current.len()];
        let mut merges = Vec::new();
        for (left, right, _) in pairs {
            if deadline_reached(deadline) {
                budget_exhausted = true;
                break;
            }
            if used[left] || used[right] {
                continue;
            }
            if let Some(merged) = MatchingPatcher::try_find_guided_2opt_merge(
                &current[left],
                &current[right],
                guide,
                g,
                contractor,
            ) {
                used[left] = true;
                used[right] = true;
                merges.push(merged);
            }
        }

        if budget_exhausted {
            break;
        }

        if merges.is_empty() {
            converged = true;
            break;
        }
        let mut next = Vec::with_capacity(current.len() - merges.len());
        next.extend(merges);
        for (index, cycle) in current.into_iter().enumerate() {
            if !used[index] {
                next.push(cycle);
            }
        }
        current = next;
    }

    GuidedMatchingResult {
        cycles: current,
        budget_exhausted,
        rounds,
        round_limit_reached: !budget_exhausted
            && !converged
            && rounds == max_rounds,
    }
}

#[inline]
fn deadline_reached(deadline: Option<Instant>) -> bool {
    deadline.map_or(false, |limit| Instant::now() >= limit)
}

fn retry_gap(failed_attempt_streak: usize) -> usize {
    if failed_attempt_streak == 0 {
        return 0;
    }
    (1usize << failed_attempt_streak.min(6))
        .saturating_sub(1)
        .min(MAX_RETRY_GAP)
}

fn cycle_edges(cycles: &[Vec<i32>]) -> BTreeSet<Edge> {
    let mut edges = BTreeSet::new();
    for cycle in cycles {
        if cycle.len() < 2 {
            continue;
        }
        for index in 0..cycle.len() {
            let u = cycle[index];
            let v = cycle[(index + 1) % cycle.len()];
            edges.insert(canonical_edge(u, v));
        }
    }
    edges
}

fn graph_from_cycle_sets(cycle_sets: &[&[Vec<i32>]]) -> Graph {
    let mut vertices = BTreeSet::new();
    let mut edges = BTreeSet::new();
    for cycles in cycle_sets {
        for cycle in *cycles {
            vertices.extend(cycle.iter().copied());
        }
        edges.extend(cycle_edges(cycles));
    }

    let mut graph = Graph::new();
    for vertex in vertices {
        graph.adjacency_list.entry(vertex).or_default();
        graph.adjacency_list_btree.entry(vertex).or_default();
    }
    for (u, v) in edges {
        graph.add_edge(u, v);
    }
    graph
}

fn canonical_edge(u: i32, v: i32) -> Edge {
    if u < v { (u, v) } else { (v, u) }
}

fn is_valid_cycle_cover(cycles: &[Vec<i32>], g: &Graph) -> bool {
    if cycles.is_empty() {
        return false;
    }
    let expected: HashSet<i32> = g.adjacency_list.keys().copied().collect();
    let mut seen = HashSet::with_capacity(expected.len());
    for cycle in cycles {
        if cycle.len() < 3 {
            return false;
        }
        for index in 0..cycle.len() {
            let u = cycle[index];
            let v = cycle[(index + 1) % cycle.len()];
            if !seen.insert(u)
                || !g
                    .adjacency_list
                    .get(&u)
                    .map_or(false, |neighbors| neighbors.contains(&v))
            {
                return false;
            }
        }
    }
    seen == expected
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::time::Duration;

    fn build_graph(edges: &[(i32, i32)]) -> Graph {
        let mut graph = Graph::new();
        for &(u, v) in edges {
            graph.add_edge(u, v);
        }
        graph
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

    fn empty_hubs() -> HubRegistry {
        HubRegistry {
            is_hub: Vec::new(),
            hub_vertices: Vec::new(),
            hub_neighbors: HashMap::new(),
            min_hub_degree: 3,
        }
    }

    #[test]
    fn recombines_two_non_hamiltonian_parents_into_one_cycle() {
        let parent = vec![vec![1, 2, 4], vec![3, 5, 6]];
        let current = vec![vec![1, 2, 3], vec![4, 5, 6]];
        let graph = build_graph(&[
            (1, 2), (2, 4), (4, 1),
            (3, 5), (5, 6), (6, 3),
            (2, 3), (3, 1),
            (4, 5), (6, 4),
        ]);
        let contractor = empty_contractor();
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(13, 4);

        let first = population.patch_and_observe(&parent, &graph, &contractor, &hubs);
        assert_eq!(first.parents_tried, 0);
        assert_eq!(first.population_size_after, 1);

        let second = population.patch_and_observe(&current, &graph, &contractor, &hubs);
        assert_eq!(second.parents_tried, 1);
        assert_eq!(second.cycles.len(), 1);
        assert!(is_valid_cycle_cover(&second.cycles, &graph));
    }

    #[test]
    fn population_deduplicates_rotated_and_reversed_covers() {
        let graph = build_graph(&[
            (1, 2), (2, 3), (3, 1),
            (4, 5), (5, 6), (6, 4),
        ]);
        let contractor = empty_contractor();
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(3, 1);

        population.patch_and_observe(
            &[vec![1, 2, 3], vec![4, 5, 6]],
            &graph,
            &contractor,
            &hubs,
        );
        population.patch_and_observe(
            &[vec![3, 2, 1], vec![5, 6, 4]],
            &graph,
            &contractor,
            &hubs,
        );
        assert_eq!(population.len(), 1);
    }

    #[test]
    fn recombination_preserves_degree2_protected_edges() {
        let parent = vec![vec![1, 2, 4], vec![3, 5, 6]];
        let current = vec![vec![1, 2, 3], vec![4, 5, 6]];
        let graph = build_graph(&[
            (1, 2), (2, 4), (4, 1),
            (3, 5), (5, 6), (6, 3),
            (2, 3), (3, 1),
            (4, 5), (6, 4),
        ]);
        let mut contractor = empty_contractor();
        contractor.chain_map.insert((1, 2), vec![100]);
        contractor.chain_map.insert((2, 3), vec![101]);
        contractor.chain_map.insert((3, 1), vec![102]);
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(13, 4);

        population.patch_and_observe(&parent, &graph, &contractor, &hubs);
        let result = population.patch_and_observe(&current, &graph, &contractor, &hubs);
        assert_eq!(result.cycles, current);
        assert!(is_valid_cycle_cover(&result.cycles, &graph));
    }

    #[test]
    fn invalid_cover_is_neither_recombined_nor_stored() {
        let graph = build_graph(&[
            (1, 2), (2, 3), (3, 1),
            (3, 4), (4, 1),
        ]);
        let contractor = empty_contractor();
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(13, 4);
        let invalid = vec![vec![1, 2, 3]];

        let result = population.patch_and_observe(&invalid, &graph, &contractor, &hubs);
        assert_eq!(result.cycles, invalid);
        assert_eq!(result.parents_tried, 0);
        assert_eq!(population.len(), 0);
    }

    #[test]
    fn expired_deadline_skips_recombination_without_losing_soundness() {
        let parent = vec![vec![1, 2, 4], vec![3, 5, 6]];
        let current = vec![vec![1, 2, 3], vec![4, 5, 6]];
        let graph = build_graph(&[
            (1, 2), (2, 4), (4, 1),
            (3, 5), (5, 6), (6, 3),
            (2, 3), (3, 1),
            (4, 5), (6, 4),
        ]);
        let contractor = empty_contractor();
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(13, 4);
        population.patch_and_observe(&parent, &graph, &contractor, &hubs);

        let expired = Instant::now()
            .checked_sub(Duration::from_secs(1))
            .expect("Instant must support a one-second look-back");
        let result = population.patch_and_observe_until(
            &current,
            &graph,
            &contractor,
            &hubs,
            expired,
        );

        assert!(result.budget_exhausted);
        assert_eq!(result.parents_tried, 0);
        assert_eq!(result.outer_rounds, 0);
        assert_eq!(result.cycles, current);
        assert!(is_valid_cycle_cover(&result.cycles, &graph));
    }

    #[test]
    fn parent_selection_prefers_more_crossing_edges_and_respects_limit() {
        let current = vec![vec![1, 2, 3], vec![4, 5, 6], vec![7, 8, 9]];
        let no_crossing = current.clone();
        let four_crossings = vec![vec![1, 2, 4, 5, 3, 6], vec![7, 8, 9]];
        let nine_crossings = vec![vec![1, 4, 7, 2, 5, 8, 3, 6, 9]];
        let mut population = PopulationPatcher::new(5, 2);
        population.observe(&no_crossing);
        population.observe(&four_crossings);
        population.observe(&nine_crossings);

        assert_eq!(population.select_parents(&current), vec![2, 1]);
    }

    #[test]
    fn full_population_preserves_elite_and_replaces_oldest_non_elite() {
        let elite = vec![vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]];
        let older_non_elite = vec![vec![1, 2, 3, 4, 5, 6], vec![7, 8, 9, 10, 11, 12]];
        let newest = vec![
            vec![1, 2, 3],
            vec![4, 5, 6],
            vec![7, 8, 9, 10, 11, 12],
        ];
        let elite_edges = cycle_edges(&elite);
        let older_edges = cycle_edges(&older_non_elite);
        let newest_edges = cycle_edges(&newest);
        let mut population = PopulationPatcher::new(2, 1);

        population.observe(&elite);
        population.observe(&older_non_elite);
        population.observe(&newest);

        assert_eq!(population.len(), 2);
        assert!(population.entries.iter().any(|entry| entry.edges == elite_edges));
        assert!(population.entries.iter().any(|entry| entry.edges == newest_edges));
        assert!(!population.entries.iter().any(|entry| entry.edges == older_edges));
    }

    #[test]
    fn repeated_failures_activate_cooldown_but_still_observe_cover() {
        let parent = vec![vec![1, 2, 4], vec![3, 5, 6]];
        let current = vec![vec![1, 2, 3], vec![4, 5, 6]];
        let graph = build_graph(&[
            (1, 2), (2, 4), (4, 1),
            (3, 5), (5, 6), (6, 3),
            (2, 3), (3, 1),
            (4, 5), (6, 4),
        ]);
        let mut contractor = empty_contractor();
        contractor.chain_map.insert((1, 2), vec![100]);
        contractor.chain_map.insert((2, 3), vec![101]);
        contractor.chain_map.insert((3, 1), vec![102]);
        let hubs = empty_hubs();
        let mut population = PopulationPatcher::new(13, 4);
        population.patch_and_observe(&parent, &graph, &contractor, &hubs);

        let failed = population.patch_and_observe(&current, &graph, &contractor, &hubs);
        assert_eq!(failed.parents_tried, 1);
        assert_eq!(failed.improvements, 0);
        assert!(!failed.cooldown_skipped);

        let skipped = population.patch_and_observe(&current, &graph, &contractor, &hubs);
        assert!(skipped.cooldown_skipped);
        assert_eq!(skipped.parents_tried, 0);
        assert_eq!(skipped.cycles, current);
        assert_eq!(population.len(), 2, "the current cover is retained during cooldown");

        let expired = Instant::now()
            .checked_sub(Duration::from_secs(1))
            .expect("Instant must support a one-second look-back");
        let stopped = population.patch_and_observe_until(
            &current,
            &graph,
            &contractor,
            &hubs,
            expired,
        );
        assert!(stopped.budget_exhausted);
        assert!(!stopped.cooldown_skipped);
        assert_eq!(stopped.parents_tried, 0);
        assert_eq!(stopped.cycles, current);
    }
}
