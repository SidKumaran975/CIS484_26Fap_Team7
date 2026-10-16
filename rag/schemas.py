from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RubricCriterion(BaseModel):
    id: str
    description: str
    required: bool = True


class Question(BaseModel):
    id: str
    prompt: str
    objectives: list[str] = Field(default_factory=list)
    rubric: list[RubricCriterion]


class AssessmentDefinition(BaseModel):
    course_id: str
    title: str
    objectives: dict[str, str]
    questions: list[Question]

    @model_validator(mode="after")
    def validate_references(self):
        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Question IDs must be unique")
        for question in self.questions:
            missing = set(question.objectives) - set(self.objectives)
            if missing:
                raise ValueError(
                    f"Question {question.id} references unknown objectives: "
                    f"{', '.join(sorted(missing))}"
                )
        return self

    def question_by_id(self, question_id: str) -> Question:
        for question in self.questions:
            if question.id == question_id:
                return question
        raise KeyError(question_id)


class Citation(BaseModel):
    source: str
    locator: str
    chunk_id: str


class RetrievedChunk(Citation):
    text: str
    score: float
    source_type: str


class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["met", "partial", "not_met", "insufficient_evidence"]
    student_evidence: str = ""
    reason: str


class Evaluation(BaseModel):
    criterion_results: list[CriterionResult]
    misconceptions: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    uncertainty: Literal["low", "medium", "high"]
    uncertainty_reason: str = ""
    suggested_follow_up: str = ""
    citations: list[Citation] = Field(default_factory=list)


class CourseStatus(BaseModel):
    ready: bool
    course_id: str | None = None
    title: str | None = None
    question_count: int = 0
    document_count: int = 0
    chunk_count: int = 0
    indexed_at: str | None = None
    message: str = ""
