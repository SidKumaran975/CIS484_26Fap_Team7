"""Attainment report for one student's oral assessment.

Builds the four-part report Dr. Babik sketched for a given student:

    Essential question | Actual question(s) | Transcript text | Evaluation

* Essential question: the professor's question from the published exam.
* Actual question(s): what the examiner actually asked for it, meaning the
  opening prompt plus any follow-ups (probe, clarify, deepen).
* Response: the student's transcribed answer to each actual question.
* Evaluation: the saved grading for each individual interaction. Question
  totals additionally summarize attainment across its turns.

This module only reads data. It does not create or change any tables, so it
works with the current session store and with the unified database, which
keeps ``assessment_sessions`` and ``assessment_turns`` as compatibility views.
"""

from __future__ import annotations

import json
from typing import Any

# Best status first. A key point keeps the best status reached in any turn,
# so a follow-up that draws out a missing idea counts toward attainment.
STATUS_RANK = {"met": 3, "partial": 2, "not_met": 1, "insufficient_evidence": 0}
STATUS_LABELS = {
    "met": "Met",
    "partial": "Partially met",
    "not_met": "Not met",
    "insufficient_evidence": "Not enough evidence",
    "not_assessed": "Not assessed",
}
UNCERTAINTY_RANK = {"low": 0, "medium": 1, "high": 2}
FOLLOW_UP_LABELS = {
    "probe": "Follow-up: probe for missing points",
    "clarify": "Follow-up: ask the student to clarify",
    "deepen": "Follow-up: address a misconception",
}


def load_turns(store: Any, session_id: str) -> list[dict]:
    """Read every turn of one session, including its evaluation, in order."""
    with store._connection() as connection:
        rows = connection.execute(
            "SELECT t.question_id, t.turn_number, t.prompt, t.transcript, t.action, "
            "t.evaluation_json, t.created_at, i.EssentialQuestion AS essential_question, "
            "clip.RespClip AS recording_id, clip.Duration AS recording_duration, "
            "t.id AS interaction_id, (i.ActualQuestionVid IS NOT NULL AND i.ActualQuestionVid != '') AS has_question_video "
            "FROM assessment_turns t "
            "JOIN INTERACTION i ON i.InteractionID = t.id "
            "LEFT JOIN CLIP_RESP clip ON clip.InteractionID = t.id "
            "AND clip.AudioFilePath IS NOT NULL "
            "WHERE t.session_id = ? ORDER BY t.turn_number",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _parse_evaluation(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _phrasing(essential: str, actual: str, turn_index: int, previous_action: str) -> str:
    """Describe how an actual question relates to its essential question."""
    if turn_index > 0:
        return FOLLOW_UP_LABELS.get(previous_action, "Follow-up")
    same = " ".join(essential.split()).casefold() == " ".join(actual.split()).casefold()
    return "Asked as written" if same else "Rephrased"


def _question_attainment(key_points: list[dict], turns: list[dict]) -> dict:
    """Combine every turn's grading into one result per key point."""
    best: dict[str, dict] = {}
    misconceptions: list[str] = []
    uncertainty = None
    for turn in turns:
        evaluation = turn["evaluation"]
        for result in evaluation.get("criterion_results", []) or []:
            criterion_id = str(result.get("criterion_id", ""))
            status = str(result.get("status", ""))
            if status not in STATUS_RANK:
                continue
            current = best.get(criterion_id)
            if current is None or STATUS_RANK[status] > STATUS_RANK[current["status"]]:
                best[criterion_id] = {
                    "status": status,
                    "evidence": str(result.get("student_evidence", "") or ""),
                    "reason": str(result.get("reason", "") or ""),
                    "turn_number": turn["turn_number"],
                }
        for item in evaluation.get("misconceptions", []) or []:
            text = str(item).strip()
            if text and text not in misconceptions:
                misconceptions.append(text)
        level = evaluation.get("uncertainty")
        if level in UNCERTAINTY_RANK and (
            uncertainty is None or UNCERTAINTY_RANK[level] > UNCERTAINTY_RANK[uncertainty]
        ):
            uncertainty = level

    points = []
    for point in key_points:
        found = best.get(point["criterion_id"])
        status = found["status"] if found else "not_assessed"
        points.append(
            {
                **point,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "evidence": found["evidence"] if found else "",
                "reason": found["reason"] if found else "",
                "turn_number": found["turn_number"] if found else None,
            }
        )
    met = sum(1 for point in points if point["status"] == "met")
    partial = sum(1 for point in points if point["status"] == "partial")
    return {
        "key_points": points,
        "met": met,
        "partial": partial,
        "total": len(points),
        "summary": f"{met} of {len(points)} key points met"
        + (f", {partial} partially" if partial else ""),
        "misconceptions": misconceptions,
        "uncertainty": uncertainty,
    }


def build_attainment_report(exam: dict, session: dict, turns: list[dict]) -> dict:
    """Group a session's turns under the exam's essential questions."""
    turns_by_question: dict[str, list[dict]] = {}
    for turn in sorted(turns, key=lambda item: int(item.get("turn_number") or 0)):
        question_id = str(turn.get("question_id", ""))
        turns_by_question.setdefault(question_id, []).append(
            {
                "turn_number": int(turn.get("turn_number") or 0),
                "prompt": str(turn.get("prompt", "") or ""),
                "response": str(turn.get("transcript", "") or ""),
                "action": str(turn.get("action", "") or ""),
                "asked_at": str(turn.get("created_at", "") or ""),
                "evaluation": _parse_evaluation(turn.get("evaluation_json")),
                "essential_question": str(turn.get("essential_question") or "").strip(),
                # CLIP_RESP.RespClip: plays through /api/recordings/{recording_id}.
                "recording_id": turn.get("recording_id") or None,
                "recording_duration": turn.get("recording_duration"),
                # INTERACTION.ActualQuestionVid: plays through /api/question-videos/{interaction_id}.
                "interaction_id": turn.get("interaction_id") or None,
                "has_question_video": bool(turn.get("has_question_video")),
            }
        )

    questions = []
    for number, raw in enumerate(exam.get("questions", []) or [], start=1):
        # Same ID and key-point rules the assessment engine uses, so each
        # criterion_id in the grading matches a key point here.
        question_id = str(raw.get("id") or f"Q{number:03d}")
        essential = str(raw.get("question", "") or "").strip()
        texts = [str(p).strip() for p in raw.get("key_points", []) or [] if str(p).strip()]
        if not texts:
            texts = ["The response directly and accurately addresses the question."]
        key_points = [
            {"criterion_id": f"{question_id}_R{index}", "text": text}
            for index, text in enumerate(texts, start=1)
        ]
        question_turns = turns_by_question.get(question_id, [])
        exchanges = []
        previous_action = ""
        for index, turn in enumerate(question_turns):
            exchanges.append(
                {
                    "turn_number": turn["turn_number"],
                    "actual_question": turn["prompt"],
                    "phrasing": _phrasing(essential, turn["prompt"], index, previous_action),
                    "response": turn["response"],
                    "decision": turn["action"],
                    "asked_at": turn["asked_at"],
                    "recording_id": turn["recording_id"],
                    "recording_duration": turn["recording_duration"],
                    "interaction_id": turn["interaction_id"],
                    "question_video": turn["has_question_video"],
                    "evaluation": turn["evaluation"],
                    "attainment": _question_attainment(key_points, [turn]),
                }
            )
            previous_action = turn["action"]
        attainment = _question_attainment(key_points, question_turns)
        if not question_turns:
            # An unreached question is not a failed one.
            attainment["summary"] = "Not reached"
        questions.append(
            {
                "number": number,
                "question_id": question_id,
                "essential_question": essential,
                "reached": bool(question_turns),
                "exchanges": exchanges,
                "attainment": attainment,
            }
        )

    listed = {q["question_id"] for q in questions}
    for question_id, question_turns in turns_by_question.items():
        if question_id in listed:
            continue
        essential = next((t["essential_question"] for t in question_turns if t["essential_question"]),
                         question_turns[0]["prompt"])
        found = []
        for turn in question_turns:
            for result in turn["evaluation"].get("criterion_results", []) or []:
                criterion_id = str(result.get("criterion_id", ""))
                if criterion_id and criterion_id not in found:
                    found.append(criterion_id)
        key_points = [{"criterion_id": cid, "text": cid} for cid in found]
        exchanges = []
        previous_action = ""
        for index, turn in enumerate(question_turns):
            exchanges.append({
                "turn_number": turn["turn_number"],
                "actual_question": turn["prompt"],
                "phrasing": _phrasing(essential, turn["prompt"], index, previous_action),
                "response": turn["response"],
                "decision": turn["action"],
                "asked_at": turn["asked_at"],
                "recording_id": turn["recording_id"],
                "recording_duration": turn["recording_duration"],
                "interaction_id": turn["interaction_id"],
                "question_video": turn["has_question_video"],
                "evaluation": turn["evaluation"],
                "attainment": _question_attainment(key_points, [turn]),
            })
            previous_action = turn["action"]
        questions.append({
            "number": len(questions) + 1,
            "question_id": question_id,
            "essential_question": essential,
            "reached": True,
            "exchanges": exchanges,
            "attainment": _question_attainment(key_points, question_turns),
        })

    total_points = sum(q["attainment"]["total"] for q in questions)
    met_points = sum(q["attainment"]["met"] for q in questions)
    return {
        "session_id": str(session.get("id", "")),
        "student_name": session.get("student_name") or session.get("student_username") or "Unknown student",
        "student_username": session.get("student_username") or "",
        "exam_id": str(session.get("exam_id") or ""),
        "exam_title": str(exam.get("title") or "Oral assessment"),
        "course": str(exam.get("course") or ""),
        "started_at": session.get("created_at"),
        "completed_at": session.get("completed_at"),
        "completed": bool(session.get("completed")),
        "questions": questions,
        "totals": {
            "questions": len(questions),
            "questions_reached": sum(1 for q in questions if q["reached"]),
            "key_points": total_points,
            "key_points_met": met_points,
        },
    }
