from pathlib import Path

import yaml

from .schemas import AssessmentDefinition

ASSESSMENT_FILE = "assessment.yaml"


def load_assessment(course_dir: Path) -> AssessmentDefinition:
    assessment_path = course_dir / ASSESSMENT_FILE
    if not assessment_path.is_file():
        raise FileNotFoundError(
            f"Missing {assessment_path}. Copy assessment.example.yaml to "
            "assessment.yaml and edit it for the course."
        )
    raw = yaml.safe_load(assessment_path.read_text(encoding="utf-8"))
    return AssessmentDefinition.model_validate(raw)
