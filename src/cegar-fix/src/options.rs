use clap::{App, Arg};

pub fn get_options() -> clap::ArgMatches {
    return App::new("HPC Solver")
        .version("1.0")
        .author("Me <me@example.com>")
        .about("Solves Hamiltonian circuits")
        .arg(
            Arg::with_name("solver")
                .short('s')
                .long("solver")
                .value_name("n")
                .help("Cannot be selected, only CaDiCaL
    Solver:
    0: minisat (defalut)
    1: kissat (can't increment)
    2: cadical")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("encoding")
                .short('e')
                .long("encoding")
                .value_name("n")
                .help("Encoding method:
    0: binominal (defalut)
    1: sinz
    2: adder
    3: advanced sinz
    4: product + binominal
    5: product recursive
    6: ladder")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("input")
                .short('i')
                .long("input")
                .value_name("FILE NAME")
                .help("Input file (Required)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("output")
                .short('o')
                .long("output")
                .value_name("FOLDER NAME")
                .help("Output folder (Optional)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("blocking")
                .short('b')
                .long("block")
                .value_name("n")
                .help("Blocking method:
    0: exiting CEGAR (default)
    1: Add outgoing and incoming cut-arcs to the same clause
    2: Add existing block clauses and option 1 clause
    3: (proposed) Add cut-arcs to separate clauses
    4: Add only outgoing cut-arcs
    5: Add cut-arcs to separate clauses by only highest vertex
    6: Use exiting methods only when vertices are three or fewer
    7: Use exiting methods only when vertices are four or fewer
    8: Use exiting methods only when vertices are five or fewer
    9: Adopt the shorter between the exiting and proposed
    10: proposed and add the exiting only three vertices")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("symmetry")
                .short('y')
                .long("symmetry")
                .value_name("n")
                .help("Symmetry blocking method:
    0: No Block Symmetry option (default)
    1: Block symmetry for smallest degree vertex
    2: Block symmetry for largest degree vertex
    3: Block symmetry for smallest degree vertex by support")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("2-opt")
                .short('t')
                .long("two-opt")
                .value_name("n")
                .help("2-opt method:
    0: No 2-opt option (default)
    1: Add block clauses to subcycles found by SAT solver and to each merged subcycle
    2: Add block clauses to subcycles found by SAT solver and to most merged subcycles
    3: Add block clauses only to the most merged subcycles
    4: If even one cannot be merged, terminate and add the block sections up to that point
    5: If even one cannot be merged, terminate")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("three-opt")
                .short('x')
                .long("three-opt")
                .value_name("n")
                .help("Restricted 3-opt method:\n 0: Disabled (default)\n 1: Enabled")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("loop-prohibition")
                .short('l')
                .long("loop")
                .value_name("n")
                .help("Loop prohibition:
    0: No Loop prohibition option (default)
    1: Prohibit loops with only two vertices
    2: Prohibit loops with only three vertices
    3: Prohibit loops with two and three vertices")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("cnf-normalize")
                .short('n')
                .long("normalize")
                .value_name("n")
                .help("CNF normalization:
    0: No normalization (default)
    1: Normalize CNF")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("balanced")
                .short('c')
                .long("balanced")
                .value_name("n")
                .help("Block clauses balanced:
    0: No balanced option (default)
    1: Equalize block clauses for in-arcs and out-arcs
    2: Equalize after adding original block clauses")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("de-arcify")
                .short('d')
                .long("de-arcify")
                .value_name("n")
                .help("Remove redundant arcs:
    0: No de-arcify option (default)
    1: Remove redundant arcs before encoding
    2: hint and 1")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("set-configration")
                .long("set-configration")
                .value_name("n")
                .help("cadical set configration:
    0: (default)
    1: Set internal options to target satisfiable instances")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("degree-order")
                .short('r')
                .long("degree_order")
                .value_name("n")
                .help("clauses order:
    0: (default)
    1: ascending order by degree
    2: descending order by degree")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("arcs-order")
                .short('a')
                .long("arc_order")
                .value_name("n")
                .help("literal number order:
    0: (default)
    1: ascending order by degree
    2: descending order by degree")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("cegar-fallback")
                .short('f')
                .long("cegar-fallback")
                .value_name("n")
                .help("CEGAR hard blocking fallback option:\n 0: Disabled (default)\n 1: Enabled")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("mtz-stall")
                .long("mtz-stall")
                .value_name("n")
                .help("Partial MTZ injection stall threshold:\n 0: Disabled (default)\n N: Inject MTZ after N stall iterations")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("adaptive-escalation")
                .short('A')
                .long("adaptive-escalation")
                .value_name("n")
                .help("Adaptive stall-based escalation strategy:\n 0: Disabled\n 1: Enabled (default)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("sub-hcp-timeout")
                .long("sub-hcp-timeout")
                .value_name("n")
                .help("Sub-HCP solver timeout per cluster in seconds (default: 60)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("max-cluster-size")
                .long("max-cluster-size")
                .value_name("n")
                .help("Maximum vertices per cluster for sub-HCP solving (default: 500)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("two-tier")
                .long("two-tier")
                .value_name("n")
                .help("Two-tier demand-coordinated solver:\n 0: Disabled (default)\n 1: Enabled")
                .takes_value(true)
                .min_values(0),
        )
        .arg(
            Arg::with_name("staged-smt")
                .long("staged-smt")
                .value_name("n")
                .help("Staged-length lazy SMT solver:\n 0: Disabled (default)\n 1: Enabled")
                .takes_value(true)
                .min_values(0),
        )
        .arg(
            Arg::with_name("timeout")
                .long("timeout")
                .value_name("SECONDS")
                .help("Timeout in seconds (default: 1800.0)")
                .takes_value(true),
        )
        .arg(
            Arg::with_name("output-tour")
                .long("output-tour")
                .value_name("FILE")
                .help("Output HCP tour file path (default: scratch/graph950/found_tour_rust.hcp)")
                .takes_value(true),
        )
        .arg(feature_arg("degree2-triangle-prune", "Prune degree-2 triangle shortcut edges"))
        .arg(feature_arg("degree2-contraction", "Contract maximal degree-2 paths"))
        .arg(feature_arg("global-short-cuts", "Add global triangle and 4-cycle cuts"))
        .arg(feature_arg("short-cycle-sec", "Add enhanced SEC clauses for short CEGAR subcycles"))
        .arg(feature_arg("cluster-cuts", "Add dense cluster cut constraints"))
        .arg(feature_arg("modular-prepass", "Run modular-decomposition prepass"))
        .arg(feature_arg("hub-partition-prepass", "Run hub-partitioned sub-HCP prepass"))
        .arg(feature_arg("hub-patcher", "Run hub-aware cycle patcher"))
        .arg(feature_arg("matching-patcher", "Run matching cycle patcher"))
        .arg(feature_arg("chained-lk", "Run chained Lin-Kernighan patcher"))
        .arg(feature_arg("ils-patcher", "Run iterated-local-search patcher"))
        .arg(feature_arg("macro-patcher", "Run macro-graph patcher"))
        .arg(
            Arg::with_name("telemetry")
                .long("telemetry")
                .value_name("0|1")
                .help("Emit machine-readable per-phase metric lines (default: 0)")
                .takes_value(true),
        )
        .get_matches();
}

fn feature_arg(name: &'static str, help: &'static str) -> Arg<'static> {
    Arg::with_name(name)
        .long(name)
        .value_name("0|1")
        .help(help)
        .takes_value(true)
}


//実行方法
// cargo run -- --solver 1 --encoding 2
// cargo run -- -s 1 -e 2
// cargo run
