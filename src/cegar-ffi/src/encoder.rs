use crate::graph::*;
use crate::hcp_solver::{Solver, Solver_add};
use std::collections::{BTreeMap, BTreeSet};

pub struct Encoder {
    pub graph_lit_map: BTreeMap<(i32, i32), Lit>, //キー：有向辺i->j (i,j)、値：s_i_jのリテラル
    // pub new_lit_map: BTreeMap<(usize, usize), Lit>, //キー：？？、値：s_i_jのリテラル
    // pub edge_map: HashMap<(i32,i32),Lit>,
    pub instance: Instance,
}

impl Encoder {
    pub fn new() -> Self {
        Self {
            graph_lit_map: BTreeMap::new(),
            // new_lit_map: BTreeMap::new(),
            // edge_map: HashMap::new(),
            instance: Instance::new(),
        }
    }

    pub fn encode(&mut self,solver:*mut Solver, g: &Graph, symmetry: i32, loop_prohibition: i32, degree_order:i32, arcs_order:i32) {
        // let mut cnf = Cnf::new();
        self.instance.new_lit();
        //有向辺に対応するリテラルを作成
        let arcs = match arcs_order{
            1 => {
                let mut sorted_arcs = g.arcs.clone();
                sorted_arcs.sort_by(|a, b| { 
                    let min_a = std::cmp::min(g.adjacency_list.get(&a.0).unwrap().len(), g.adjacency_list.get(&a.1).unwrap().len()); 
                    let min_b = std::cmp::min(g.adjacency_list.get(&b.0).unwrap().len(), g.adjacency_list.get(&b.1).unwrap().len()); 
                    if min_a == min_b { 
                        let other_a = std::cmp::max(g.adjacency_list.get(&a.0).unwrap().len(), g.adjacency_list.get(&a.1).unwrap().len()); 
                        let other_b = std::cmp::max(g.adjacency_list.get(&b.0).unwrap().len(), g.adjacency_list.get(&b.1).unwrap().len()); 
                        other_a.cmp(&other_b) // 昇順 
                    } else {
                        min_a.cmp(&min_b) // 昇順
                    } 
                });
                sorted_arcs
            },
            2 => {
                let mut sorted_arcs = g.arcs.clone();
                sorted_arcs.sort_by(|a, b| { 
                    let max_a = std::cmp::max(g.adjacency_list.get(&a.0).unwrap().len(), g.adjacency_list.get(&a.1).unwrap().len()); 
                    let max_b = std::cmp::max(g.adjacency_list.get(&b.0).unwrap().len(), g.adjacency_list.get(&b.1).unwrap().len()); 
                    if max_a == max_b { 
                        let other_a = std::cmp::min(g.adjacency_list.get(&a.0).unwrap().len(), g.adjacency_list.get(&a.1).unwrap().len()); 
                        let other_b = std::cmp::min(g.adjacency_list.get(&b.0).unwrap().len(), g.adjacency_list.get(&b.1).unwrap().len()); 
                        other_b.cmp(&other_a) // 降順 
                    } else {
                         max_b.cmp(&max_a) // 降順 
                    } 
                });
                sorted_arcs
            }
            _ => g.arcs.clone(),   
        };

        for &(u, v) in arcs.iter() {
            let lit = self.instance.new_lit();
            self.graph_lit_map.insert((u, v), lit);
        }

        let neighbors_zip = match degree_order{
            0 => g.adjacency_list_btree.iter().collect::<Vec<_>>(),
            1 => {
                let mut map_vec = g.adjacency_list_btree.iter().collect::<Vec<_>>();
                //昇順に並べる
                map_vec.sort_by(|a, b| a.1.len().cmp(&b.1.len()));
                map_vec
            },
            2 => {
                let mut map_vec = g.adjacency_list_btree.iter().collect::<Vec<_>>();
                //昇順に並べる
                map_vec.sort_by(|a, b| b.1.len().cmp(&a.1.len()));
                map_vec
            },
            _ => vec!()
        };

        //次数制約をcnfに追加
        for (&u, neighbors) in neighbors_zip {
            let mut out_lits = Vec::new();
            let mut in_lits = Vec::new();
            for &v in neighbors {
                out_lits.push(self.graph_lit_map[&(u, v)]);
                in_lits.push(self.graph_lit_map[&(v, u)]);
            }
            //入次数と出次数のexact-oneをcnfに追加する
            self.exact_one(solver, &out_lits);
            self.exact_one(solver, &in_lits);
        }



        if loop_prohibition == 1{
            //二つの頂点だけのループを防ぐ
            self.two_loop_prohibition(solver,&g);
        // }else if loop_prohibition == 2{
        //     //三つの頂点だけのループを防ぐ
        //     cnf.extend(self.three_loop_prohibition(&g));
        // }else if loop_prohibition == 3{
        //     //二つの頂点のループと三つの頂点のループを防ぐ
        //     cnf.extend(self.two_loop_prohibition(&g));
        //     cnf.extend(self.three_loop_prohibition(&g));
        }

        //対称性の除去
        if symmetry == 1 {
            //次数が一番小さい頂点に対して対称性を禁止する
            let lowest_vertex = g.get_lowest_degree_vertex();
            let clauses = self.asymmetry(solver, lowest_vertex, &g.adjacency_list[&lowest_vertex],symmetry);
            Encoder::clauses_add(solver, &clauses);
        } else if symmetry == 2 {
            //次数が一番大きい頂点に対して対称性を禁止する
            let highest_vertex = g.get_highest_degree_vertex();
            let clauses = self.asymmetry(solver,highest_vertex, &g.adjacency_list[&highest_vertex],symmetry);
            Encoder::clauses_add(solver, &clauses);
        } else if symmetry == 3{
            //次数が一番小さい頂点に対してサポート節を加える
            let lowest_vertex = g.get_lowest_degree_vertex();
            let clauses = self.asymmetry(solver,lowest_vertex, &g.adjacency_list[&lowest_vertex],symmetry);
            Encoder::clauses_add(solver, &clauses);
        } else if symmetry == 4{
            //次数が一番小さい頂点に対してサポート節を加える
            let lowest_vertex = g.get_lowest_degree_vertex();
            let clauses = self.asymmetry(solver,lowest_vertex, &g.adjacency_list[&lowest_vertex],symmetry);
            // Encoder::clauses_add(solver, &clauses);
        }

        // if dearcify > 1 {
        //     cnf.extend(self.dearcify(g, dearcify));
        // }

        
    }

    /// Encode exactly one selected literal with a linear Sinz counter.
    ///
    /// The upstream `cegar-ffi` expected a patched Cardinality-CDCL API named
    /// `Solver_CARadd`.  Forwarding that stream to ordinary `ccadical_add`
    /// changes a cardinality constraint into a malformed CNF clause.  Keep the
    /// portable backend on the standard CaDiCaL API and encode the constraint
    /// explicitly instead.
    pub fn exact_one(&mut self, solver: *mut Solver, lits: &[Lit]) {
        if lits.is_empty() {
            Encoder::clause_add(solver, &[]);
            return;
        }
        Encoder::clause_add(solver, lits);
        self.at_most_one_sinz(solver, lits);
    }

    fn at_most_one_sinz(&mut self, solver: *mut Solver, lits: &[Lit]) {
        if lits.len() <= 1 {
            return;
        }
        if lits.len() == 2 {
            Encoder::clause_add(solver, &[!lits[0], !lits[1]]);
            return;
        }

        let sequential: Vec<Lit> = (0..lits.len() - 1)
            .map(|_| self.instance.new_lit())
            .collect();
        Encoder::clause_add(solver, &[!lits[0], sequential[0]]);
        for index in 1..lits.len() - 1 {
            Encoder::clause_add(solver, &[!lits[index], sequential[index]]);
            Encoder::clause_add(solver, &[!sequential[index - 1], sequential[index]]);
            Encoder::clause_add(solver, &[!lits[index], !sequential[index - 1]]);
        }
        Encoder::clause_add(
            solver,
            &[!lits[lits.len() - 1], !sequential[sequential.len() - 1]],
        );
    }

    /// The only non-exact cardinality calls in this solver are `sum <= len-1`:
    /// a single no-good clause that blocks all literals from being true.
    pub fn at_most_n(solver: *mut Solver, lits: &[Lit], n: i32) {
        assert_eq!(n, lits.len() as i32 - 1, "unsupported at-most bound");
        let clause: Vec<Lit> = lits.iter().map(|lit| !*lit).collect();
        Encoder::clause_add(solver, &clause);
    }

    /// All cut-set calls request at least one boundary arc.
    pub fn at_least_n(solver: *mut Solver, lits: &[Lit], n: i32) {
        assert_eq!(n, 1, "unsupported at-least bound");
        Encoder::clause_add(solver, lits);
    }

    pub fn clauses_add(solver: *mut Solver, clauses: &[Vec<Lit>]) {
        for clause in clauses.iter(){
            Encoder::clause_add(solver, clause);
        }
    }

    pub fn clause_add(solver: *mut Solver, clause: &[Lit]) {
        unsafe {
            for lit in clause.iter() {
                Solver_add(solver, lit.get_lit());
            }
            Solver_add(solver, 0);
        }
    }

    fn asymmetry(&self, solver:*mut Solver, u: i32, adjs: &Vec<i32>,symmetry: i32) -> Vec<Vec<Lit>> {
        let mut clauses: Vec<Vec<Lit>> = Vec::new();
        let mut adjs_sort = adjs.clone();
        adjs_sort.sort();
        for (i, v_out) in adjs_sort.iter().enumerate() {
            if symmetry < 3{
                if i == 0 {
                    continue;
                } else if i == adjs_sort.len() - 1 {
                    //隣接する頂点の中で、頂点番号が一番大きい頂点へ出ていく辺を禁止する
                    let lit = self.graph_lit_map[&(u, *v_out)];
                    clauses.push(vec!(!lit));
                } else {
                    //出ていく辺よりも入ってくる辺の頂点番号のほうが小さいものを禁止する
                    for v_in in &adjs_sort[..i] {
                        let lit1 = self.graph_lit_map[&(u, *v_out)];
                        let lit2 = self.graph_lit_map[&(*v_in, u)];
                        clauses.push(vec!(!lit1, !lit2));
                    }
                }
            }else if symmetry == 3{
                if i == 0{
                    let mut clause = Vec::new();
                    for v_in in &adjs_sort[1..]{
                        let lit = self.graph_lit_map[&(*v_in,u)];
                        clause.push(lit);
                    }
                    clauses.push(clause);
                }else if i == adjs_sort.len()-1{
                    let lit = self.graph_lit_map[&(u, *v_out)];
                    clauses.push(vec!(!lit));
                }else{
                    let mut clause = Vec::new();
                    for v_in in &adjs_sort[i+1..]{
                        let lit = self.graph_lit_map[&(*v_in,u)];
                        clause.push(lit);
                    }
                    let lit = self.graph_lit_map[&(u, *v_out)];
                    clause.push(!lit);
                    clauses.push(clause);
                }
            }else{
                if i == 0{
                    let mut clause = Vec::new();
                    for v_in in &adjs_sort[1..]{
                        let lit = self.graph_lit_map[&(*v_in,u)];
                        clause.push(lit);
                    }
                    Encoder::at_least_n(solver, &clause, 1);
                    clauses.push(clause);
                    let lit1 = self.graph_lit_map[&(adjs_sort[0],u)];
                    Encoder::at_most_n(solver, &vec!(lit1), 0);
                }else if i == adjs_sort.len()-1{
                    let lit = self.graph_lit_map[&(u, *v_out)];
                    let clause = vec!(!lit);
                    Encoder::at_least_n(solver, &clause, 1);
                    clauses.push(clause);
                }else{
                    let mut clause = Vec::new();
                    for v_in in &adjs_sort[i+1..]{
                        let lit = self.graph_lit_map[&(*v_in,u)];
                        clause.push(lit);
                    }
                    let lit = self.graph_lit_map[&(u, *v_out)];
                    clause.push(!lit);
                    Encoder::at_least_n(solver, &clause, 1);
                    clauses.push(clause);
                }
            }
        }

        clauses
    }

    fn two_loop_prohibition(&mut self,solver:*mut Solver, g:&Graph){
        // let mut clauses = Vec::new();
        let mut memo: BTreeSet<(i32, i32)> = BTreeSet::new();
            for &(u, v) in g.arcs.iter() {
                if memo.contains(&(u, v)) {
                    continue;
                } else {
                    let lit1 = self.graph_lit_map[&(u, v)];
                    let lit2 = self.graph_lit_map[&(v, u)];
                    // clauses.push(clause!(!lit1, !lit2));
                    Encoder::at_most_n(solver,&vec!(lit1,lit2), 1);
                    memo.insert((v, u));
                }
            }
    }

    // fn three_loop_prohibition(&self, g:&Graph) -> Vec<Clause>{
    //     let mut clauses = Vec::new();
    //     let mut memo: Vec<BTreeSet<i32>> = Vec::new();
    //     // let mut two_memo: BTreeSet<BTreeSet<i32>> = BTreeSet::new();
    //     // let mut one_memo: BTreeSet<i32> = BTreeSet::new()

    //     for x in g.adjacency_list.keys() {
    //         for ys in g.adjacency_list.get(&x).iter(){
    //             for y in ys.iter(){
    //                 let bool1 = memo.contains(&BTreeSet::from([*y]));
    //                 let bool2 = memo.contains(&BTreeSet::from([*x,*y]));
    //                 if  !bool1 && !bool2 {
    //                     for zs in g.adjacency_list.get(&y).iter(){
    //                         for z in zs.iter(){
    //                             if ys.contains(z){
    //                                 let bool3 = x == z;
    //                                 let bool4 = memo.contains(&BTreeSet::from([*x,*y,*z]));
    //                                 let bool5 = memo.contains(&BTreeSet::from([*y,*z]));
    //                                 let bool6 = memo.contains(&BTreeSet::from([*x,*z]));
    //                                 let bool7 = memo.contains(&BTreeSet::from([*z]));
                                    
    //                                 if  !bool3 && !bool4 && !bool5 && !bool6 && !bool7{
    //                                     //順方向
    //                                     let lit1 = self.graph_lit_map[&(*x, *y)];
    //                                     let lit2 = self.graph_lit_map[&(*y, *z)];
    //                                     let lit3 = self.graph_lit_map[&(*z, *x)];
    //                                     clauses.push(clause!(!lit1,!lit2,!lit3));

    //                                     //逆方向
    //                                     let lit4 = self.graph_lit_map[&(*x, *z)];
    //                                     let lit5 = self.graph_lit_map[&(*y, *x)];
    //                                     let lit6 = self.graph_lit_map[&(*z, *y)];
    //                                     clauses.push(clause!(!lit4,!lit5,!lit6));
                                        
    //                                     memo.push(BTreeSet::from([*x,*y,*z]));
    //                                 }
    //                             }
    //                         }
    //                     }
    //                 }
    //                 memo.push(BTreeSet::from([*x,*y]));
    //             }
    //         }
    //         memo.push(BTreeSet::from([*x]));
    //     }

    //     clauses


    // }

    // fn dearcify(&mut self,g:&Graph,method: i32) -> Vec<Clause>{
    //     let mut clauses = Vec::new();
    //     let degrees = match method{
    //         2 => vec![2,3,4],
    //         3 => vec![2,3],
    //         _ => vec![2],
    //     };

    //     for (u,adj) in g.adjacency_list_btree.iter(){
    //         match Encoder::is_adjacent_to_degree(adj,g,&degrees){
    //             Some(low_verticies) => {
    //                 clauses.extend(self.dearcify_encode(g, *u, low_verticies))
    //             },
    //             None => ()
    //         }
    //     }
    //     clauses
    // }

    // fn is_adjacent_to_degree(adjs:&Vec<i32>,g:&Graph,degrees:&Vec<i32>) -> Option<Vec<i32>>{

    //     if adjs.len() == 2{
    //         return None
    //     }
        
    //     let mut specified_degree_verticies = Vec::new();
    //     for adj in adjs.iter(){
    //         let adj_degree = g.adjacency_list.get(adj).unwrap().len() as i32;
    //         if degrees.contains(&adj_degree){
    //             specified_degree_verticies.push(*adj);
    //         }
    //     }

    //     if specified_degree_verticies.len() < 2{
    //         None
    //     }else{
    //         Some(specified_degree_verticies)
    //     }
    // }
    
    // fn dearcify_encode(&mut self,g:&Graph,u:i32,low_verticies:Vec<i32>) -> Vec<Clause>{
    //     let mut clauses = Vec::new();
    //     let mut adjs_lits = Vec::new();
    //     let mut verticies_of_degree_two = Vec::new();

    //     for low_vertex in low_verticies.iter(){
    //         let low_adjs = g.adjacency_list.get(low_vertex).unwrap();
    //         if low_adjs.len() == 2{
    //             verticies_of_degree_two.push(*low_vertex);
    //         }else{
    //             let (clause,lit) = self.activate_on_degree_two(u, *low_vertex, low_adjs);
    //             clauses.extend(clause);
    //             adjs_lits.push((*low_vertex,lit));
    //         }
    //     }
        
    //     match verticies_of_degree_two.len(){
    //         2 => {
    //             let u_x = *self.graph_lit_map.get(&(u,verticies_of_degree_two[0])).unwrap();
    //             let u_y = *self.graph_lit_map.get(&(u,verticies_of_degree_two[1])).unwrap();
    //             let x_u = *self.graph_lit_map.get(&(verticies_of_degree_two[0],u)).unwrap();
    //             let y_u = *self.graph_lit_map.get(&(verticies_of_degree_two[1],u)).unwrap();
    //             clauses.push(clause!(u_x,u_y));
    //             clauses.push(clause!(x_u,y_u));
    //         },
    //         1 => {
    //             let u_x = *self.graph_lit_map.get(&(u,verticies_of_degree_two[0])).unwrap();
    //             let x_u = *self.graph_lit_map.get(&(verticies_of_degree_two[0],u)).unwrap();
    //             for (y,lit) in adjs_lits.iter() {
    //                 let u_y = *self.graph_lit_map.get(&(u,*y)).unwrap();
    //                 let y_u = *self.graph_lit_map.get(&(*y,u)).unwrap();
    //                 clauses.push(clause!(!*lit,u_x,u_y));
    //                 clauses.push(clause!(!*lit,x_u,y_u));
    //             }
    //         },
    //         _ => {
    //             for i in 0..adjs_lits.len(){
    //                 let (x,x_lit) = adjs_lits[i];
    //                 let u_x = *self.graph_lit_map.get(&(u,x)).unwrap();
    //                 let x_u = *self.graph_lit_map.get(&(x,u)).unwrap();
    //                 for j in i+1..adjs_lits.len(){
    //                     let (y,y_lit) = adjs_lits[j];
    //                     let u_y = *self.graph_lit_map.get(&(u,y)).unwrap();
    //                     let y_u = *self.graph_lit_map.get(&(y,u)).unwrap();
    //                     clauses.push(clause!(!x_lit,!y_lit,u_x,u_y));
    //                     clauses.push(clause!(!x_lit,!y_lit,x_u,y_u));
                        
    //                 }
    //             }
    //         }
    //     }
        

    //     clauses
    // }

    // fn activate_on_degree_two(&mut self,u:i32,v:i32,adjs:&Vec<i32>) -> (Vec<Clause>,Lit) {
    //     let mut clauses = Vec::new();
    //     let new_lit = self.instance.new_lit(); 
    //     let mut lits = Vec::new();
    //     let new_adjs:Vec<i32> = adjs.iter().filter(|&&x| x != u).cloned().collect();
    //     for i in 0..new_adjs.len(){
    //         let is_insert = self.insert_edge(v,new_adjs[i]);
    //         match is_insert{
    //             Some(clause) => clauses.extend(clause),
    //             None => ()
    //         }
    //     }

    //     for i in 0..new_adjs.len(){
    //         for j in i+1..new_adjs.len(){
    //             let x = new_adjs[i];
    //             let y = new_adjs[j];
    //             let lit = self.instance.new_lit();
    //             // !e1 and !e2 -> s1
    //             clauses.push(clause!(*self.edge(v,x).unwrap(),*self.edge(v,y).unwrap(),lit));

    //             // s1 -> !e1 and !e2
    //             clauses.push(clause!(!lit,!*self.edge(v,x).unwrap()));
    //             clauses.push(clause!(!lit,!*self.edge(v,y).unwrap()));

    //             lits.push(lit);
    //         }
    //     }

    //     let mut clause = Clause::new();
    //     for lit in lits.iter(){
    //         clauses.push(clause!(!*lit,new_lit));
    //         clause.add(*lit);
    //     }
    //     clause.add(!new_lit);
    //     clauses.push(clause);


    //     (clauses,new_lit)
    // }


    // fn insert_edge(&mut self,u:i32,v:i32) -> Option<Vec<Clause>> {
    //     let mut clauses = Vec::new();
        
    //     match self.edge(u,v){
    //         Some(_) => return None,
    //         None =>{
    //             let lit = self.instance.new_lit();
    //             let u_v = *self.graph_lit_map.get(&(u,v)).unwrap();
    //             let v_u = *self.graph_lit_map.get(&(v,u)).unwrap();
    //             // u_v or v_u -> edge_u_v
    //             clauses.push(clause!(!u_v,lit));
    //             clauses.push(clause!(!v_u,lit));
                
    //             // !u_v and !v_u -> !edge_u_v
    //             clauses.push(clause!(u_v,v_u,!lit));

    //             if u < v {
    //                 self.edge_map.insert((u,v), lit);
    //             }else{
    //                 self.edge_map.insert((v,u),lit);
    //             }

    //         }
    //     }
        

    //     Some(clauses)
    // }

    // fn edge(&self,u:i32,v:i32) -> Option<&Lit> {
    //     if u < v{
    //         self.edge_map.get(&(u,v))
    //     }else{
    //         self.edge_map.get(&(v,u))
    //     }
    // }
}

pub struct Instance {
    lits: Vec<Lit>,
    current_index: i32,
}

impl Instance {
    pub fn new() -> Self {
        Instance {
            lits: Vec::new(),
            current_index: 0,
        }
    }

    pub fn new_lit(&mut self) -> Lit {
        self.current_index += 1;
        let lit = Lit::new(self.current_index);
        self.lits.push(lit);
        lit
    }

    pub fn get_lits(&self) -> &Vec<Lit> {
        &self.lits
    }
}


#[derive(Clone, Copy, Debug)]
pub struct Lit {
    lit: i32,
}

impl Lit {
    pub fn new(lit: i32) -> Self {
        Lit { lit }
    }

    pub fn get_lit(&self) -> i32 {
        self.lit
    }

    pub fn is_pos(&self) -> bool {
        self.lit > 0
    }

    pub fn is_neg(&self) -> bool {
        self.lit < 0
    }

    pub fn var(&self) -> i32 {
        self.lit.abs()
    }
}

impl std::ops::Not for Lit {
    type Output = Lit;

    fn not(self) -> Lit {
        Lit::new(-self.lit)
    }
}
