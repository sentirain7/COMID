"""V7 구조 ML champion 활성화 (A3) — 165 내부 데이터로 첫 challenger 등록·경쟁.

우리 GAFF2 bulk 데이터로 V7 challenger를 학습(물성별 XGB-vs-RF 승자)하고
registry에 등록한 뒤, density holdout에서 V3 champion과 교차 피처셋 비교한다.
V7이 이기고 **champion 커버리지를 떨어뜨리지 않으면** 승급(Decision A).

⚠️ 이 스크립트는 production registry(asphalt_agent.db)를 수정한다.
dry-run은 ``--no-register``.

사용:
  PYTHONPATH=src:packages python scripts/activate_v7_champion.py [--no-register] \
      [--db sqlite:///asphalt_agent.db] [--targets density ...]
"""

import argparse
import json
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="sqlite:///asphalt_agent.db")
    p.add_argument("--targets", nargs="+", default=None, help="기본: V7 적격 전체")
    p.add_argument("--no-register", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ml.structural_challenger import train_structural_challenger

    session = sessionmaker(bind=create_engine(args.db))()
    try:
        outcome = train_structural_challenger(
            session, targets=args.targets, register=not args.no_register
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
