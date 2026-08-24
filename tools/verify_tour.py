#!/usr/bin/env python3
"""Independently verify an HCP/TSPLIB tour against a .col graph."""

from __future__ import annotations

import argparse
from pathlib import Path

from hcp_benchmark import graph_features, parse_tour_file, verify_tour


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("tour", type=Path)
    args = parser.parse_args()
    features, vertices, edges = graph_features(args.graph.resolve())
    tour = parse_tour_file(args.tour.resolve())
    valid, reason = verify_tour(tour, vertices, edges)
    print(
        f"valid={str(valid).lower()} reason={reason} "
        f"vertices={features['vertices']} tour_vertices={len(tour) if tour else 0}"
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
