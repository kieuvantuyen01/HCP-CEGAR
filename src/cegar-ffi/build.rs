use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn cadical_library_dir(path: &Path) -> Option<PathBuf> {
    path.join("libcadical.a").is_file().then(|| path.to_path_buf())
}

fn rustsat_cadical_library(target_dir: &Path) -> Option<PathBuf> {
    for profile in ["release", "debug"] {
        let build_dir = target_dir.join(profile).join("build");
        let Ok(entries) = fs::read_dir(build_dir) else {
            continue;
        };
        let mut candidates: Vec<PathBuf> = entries
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("rustsat-cadical-")
            })
            .filter_map(|entry| cadical_library_dir(&entry.path().join("out")))
            .collect();
        candidates.sort();
        if let Some(candidate) = candidates.pop() {
            return Some(candidate);
        }
    }
    None
}

fn find_cadical_library(manifest_dir: &Path) -> Option<PathBuf> {
    if let Some(directory) = env::var_os("CADICAL_DIR") {
        if let Some(found) = cadical_library_dir(Path::new(&directory)) {
            return Some(found);
        }
    }

    let cegar_fix_target = manifest_dir.join("../cegar-fix/target");
    if let Some(found) = rustsat_cadical_library(&cegar_fix_target) {
        return Some(found);
    }

    cadical_library_dir(&manifest_dir.join("../../../hcup/include/cadical/build"))
}

fn main() {
    cc::Build::new()
        .file("src/solver_wrapper.c")
        .compile("solver_wrapper");

    println!("cargo:rerun-if-env-changed=CADICAL_DIR");
    println!("cargo:rerun-if-changed=src/solver_wrapper.c");
    let manifest_dir = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR").expect("Cargo must set CARGO_MANIFEST_DIR"),
    );
    let cadical_dir = find_cadical_library(&manifest_dir).unwrap_or_else(|| {
        panic!(
            "libcadical.a not found. Build ../cegar-fix first or set CADICAL_DIR to its directory"
        )
    });
    println!(
        "cargo:rerun-if-changed={}",
        cadical_dir.join("libcadical.a").display()
    );
    println!("cargo:rustc-link-search=native={}", cadical_dir.display());
    println!("cargo:rustc-link-lib=static=cadical");

    let target = env::var("TARGET").unwrap_or_default();
    if target.contains("apple") || target.contains("freebsd") {
        println!("cargo:rustc-link-lib=dylib=c++");
    } else if !target.contains("msvc") {
        println!("cargo:rustc-link-lib=dylib=stdc++");
    }
}
