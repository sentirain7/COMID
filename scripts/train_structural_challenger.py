"""CLI: train a V7 structural challenger on our GAFF2 corpus (P3).

Usage:
  PYTHONPATH=src:packages python scripts/train_structural_challenger.py \
      [--targets density] [--db sqlite:///asphalt_agent.db] [--no-register]

Reuses DataLoader(V7) + MultiTargetPredictor + ModelRegistry. Registers the
result as a *challenger*; promotion happens only if it beats the incumbent
champion on a held-out split (Decision A).
"""

import argparse
import json
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--targets", nargs="+", default=["density"])
    p.add_argument("--db", default="sqlite:///asphalt_agent.db")
    p.add_argument("--ff-type", default="bulk_ff_gaff2")
    p.add_argument("--min-samples", type=int, default=30)
    p.add_argument("--holdout-ratio", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-register", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ml.structural_challenger import train_structural_challenger

    engine = create_engine(args.db)
    session = sessionmaker(bind=engine)()
    try:
        outcome = train_structural_challenger(
            session,
            targets=args.targets,
            ff_type=args.ff_type,
            min_samples=args.min_samples,
            holdout_ratio=args.holdout_ratio,
            random_seed=args.seed,
            register=not args.no_register,
        )
    finally:
        session.close()

    print(
        json.dumps(
            {
                "version_id": outcome.version_id,
                "targets_trained": outcome.targets_trained,
                "training_samples": outcome.training_samples,
                "holdout_samples": outcome.holdout_samples,
                "promoted": outcome.promoted,
                "comparison": outcome.comparison,
                "holdout_rmse": outcome.per_target_holdout_rmse,
                "notes": outcome.notes,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if outcome.targets_trained else 1


if __name__ == "__main__":
    sys.exit(main())
