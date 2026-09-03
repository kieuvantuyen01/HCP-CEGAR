extern void* ccadical_init(void);
extern void ccadical_release(void* ptr);
extern void ccadical_add(void* ptr, int lit);
extern int ccadical_solve(void* ptr);
extern int ccadical_val(void* ptr, int lit);

void* Solver_new(void) {
    return ccadical_init();
}

void Solver_delete(void* ptr) {
    ccadical_release(ptr);
}

void Solver_add(void* ptr, int lit) {
    ccadical_add(ptr, lit);
}

int Solver_solve(void* ptr) {
    return ccadical_solve(ptr);
}

int Solver_val(void* ptr, int lit) {
    return ccadical_val(ptr, lit);
}
