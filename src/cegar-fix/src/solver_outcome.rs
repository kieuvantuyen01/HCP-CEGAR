#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SolverOutcome {
    Sat(Vec<i32>),
    Unsat,
    Unknown(String),
    Error(String),
}

impl SolverOutcome {
    pub fn sat(tour: Vec<i32>) -> Self {
        Self::Sat(tour)
    }

    pub fn unknown(reason: impl Into<String>) -> Self {
        Self::Unknown(reason.into())
    }

    pub fn error(reason: impl Into<String>) -> Self {
        Self::Error(reason.into())
    }

    pub fn as_sat(&self) -> Option<&[i32]> {
        match self {
            Self::Sat(tour) => Some(tour),
            _ => None,
        }
    }
}
