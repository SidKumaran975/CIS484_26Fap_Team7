from .analytics import analytics_stage, current_run
from .config import Settings
from .course import load_assessment
from .evaluator import Evaluator, choose_action
from .index import CourseIndex
from .schemas import AssessmentDefinition, CourseStatus
from .sessions import SessionStore


class AssessmentEngine:
    def __init__(
        self,
        settings: Settings,
        assessment: AssessmentDefinition | None = None,
        exam_id: str | None = None,
    ):
        self.settings = settings
        self.settings.prepare_runtime_dirs()
        self.assessment = assessment or load_assessment(settings.course_content_dir)
        self.exam_id = exam_id
        self.index = CourseIndex(settings.vector_db_path, settings.embed_model)
        self.evaluator = Evaluator(settings.evaluation_model)
        self.sessions = SessionStore(settings.session_db_path)

    def close(self) -> None:
        self.index.close()

    def status(self) -> CourseStatus:
        manifest = self.index.status()
        indexed_for_course = manifest.get("course_id") == self.assessment.course_id
        embedding_matches = manifest.get("embedding_model") == self.settings.embed_model
        ready = self.index.exists() and indexed_for_course and embedding_matches
        message = "Course is ready."
        if not ready:
            message = "Course content must be published before starting an assessment."
        return CourseStatus(
            ready=ready,
            course_id=self.assessment.course_id,
            title=self.assessment.title,
            question_count=len(self.assessment.questions),
            document_count=int(manifest.get("document_count", 0)),
            chunk_count=int(manifest.get("chunk_count", 0)),
            indexed_at=manifest.get("indexed_at"),
            message=message,
        )

    def publish_course(self) -> CourseStatus:
        assessment = load_assessment(self.settings.course_content_dir)
        self.index.rebuild(
            self.settings.course_content_dir,
            assessment.course_id,
        )
        self.assessment = assessment
        return self.status()

    def start_session(self, student: dict | None = None) -> dict:
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.message)
        question = self.assessment.questions[0]
        student = student or {}
        session = self.sessions.create(
            self.assessment.course_id,
            self.exam_id,
            student_id=student.get("id"),
            student_username=student.get("username"),
            student_name=student.get("display_name"),
            initial_prompt=question.prompt,
        )
        return {
            "session_id": session["id"],
            "question_id": question.id,
            "question_number": 1,
            "question_count": len(self.assessment.questions),
            "prompt": question.prompt,
            "completed": False,
        }

    def submit_response(self, session_id: str, transcript: str, recording: dict | None = None) -> dict:
        transcript = transcript.strip()
        if not transcript:
            raise ValueError("No speech was detected. Please record the answer again.")

        session = self.sessions.get(session_id)
        if session["completed"]:
            raise ValueError("This assessment session is already complete.")

        question_index = int(session["question_index"])
        follow_up_count = int(session["follow_up_count"])
        question = self.assessment.questions[question_index]
        current_prompt = str(session.get("current_prompt") or question.prompt)
        objectives = {
            objective_id: self.assessment.objectives[objective_id]
            for objective_id in question.objectives
        }
        previous = self.sessions.transcripts_for_question(session_id, question.id)
        combined_response = "\n".join(previous + [transcript])
        query = "\n".join(
            [
                f"Question: {question.prompt}",
                "Objectives: " + " ".join(objectives.values()),
                f"Student response: {combined_response}",
            ]
        )
        with analytics_stage("retrieval"):
            retrieved = self.index.search(query, self.settings.top_k)
        with analytics_stage("rubric_evaluation"):
            evaluation = self.evaluator.evaluate(
                question,
                self.assessment.objectives,
                combined_response,
                retrieved,
            )
        recorder = current_run()
        if recorder is not None:
            recorder.add_metric("retrieved_chunks", len(retrieved))
            recorder.add_metric("student_response_words", len(transcript.split()))
        required = {criterion.id for criterion in question.rubric if criterion.required}
        action = choose_action(
            evaluation,
            required,
            follow_up_count,
            self.settings.max_follow_ups,
        )

        if action == "move_on":
            next_index = question_index + 1
            completed = next_index >= len(self.assessment.questions)
            next_prompt = ""
            next_question_id = None
            next_number = None
            if not completed:
                next_question = self.assessment.questions[next_index]
                next_prompt = next_question.prompt
                next_question_id = next_question.id
                next_number = next_index + 1
            progress = (next_index, 0, completed)
        else:
            completed = False
            next_question_id = question.id
            next_number = question_index + 1
            next_prompt = evaluation.suggested_follow_up.strip() or (
                "Please expand on the required concept that was missing from your answer."
            )
            progress = (question_index, follow_up_count + 1, False)

        turn_id = self.sessions.record_turn_and_update(
            session_id=session_id,
            question_id=question.id,
            prompt=current_prompt,
            transcript=transcript,
            evaluation=evaluation.model_dump(),
            retrieved=[chunk.model_dump() for chunk in retrieved],
            action=action,
            question_index=progress[0],
            follow_up_count=progress[1],
            completed=progress[2],
            next_prompt=next_prompt,
            recording=recording,
        )
        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "question_id": question.id,
            "transcript": transcript,
            "action": action,
            "evaluation": evaluation.model_dump(),
            "next_question_id": next_question_id,
            "question_number": next_number,
            "question_count": len(self.assessment.questions),
            "next_prompt": next_prompt,
            "completed": completed,
        }
