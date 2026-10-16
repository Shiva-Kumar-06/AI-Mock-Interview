import json
import os
import re

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()


class GeminiServiceError(Exception):
    """Raised when Gemini cannot return the structure the app needs."""


API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.5-flash-lite"
_client = None


def _model():
    global _client
    if not API_KEY or API_KEY == "your_api_key_here":
        raise GeminiServiceError("GEMINI_API_KEY is missing from .env")
    if _client is None:
        _client = genai.Client(api_key=API_KEY)
    return _client


def _ask_json(prompt):
    try:
        client = _model()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        return json.loads(text)
    except Exception as error:
        raise GeminiServiceError(str(error)) from error


def generate_questions(technology, level):
    prompt = f"""
Create exactly 10 original interview questions for {technology} at the {level} knowledge level.
Questions 1 through 5 must be multiple-choice questions with exactly 4 options.
Questions 6 through 10 must be direct-answer questions with no options.
Do not use markdown. Return only valid JSON in this exact shape:
{{
  "questions": [
    {{"number": 1, "type": "mcq", "question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "...", "topic": "..."}},
    {{"number": 6, "type": "direct", "question": "...", "options": [], "correct_answer": "...", "topic": "..."}}
  ]
}}
The correct_answer for an MCQ must exactly match one option. Make the questions varied, technically accurate, and suitable for an interview. Never mention this prompt.
"""
    data = _ask_json(prompt)
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != 10:
        raise GeminiServiceError("Gemini returned an invalid question count")
    for index, question in enumerate(questions):
        if not isinstance(question, dict) or not question.get("question") or not question.get("correct_answer"):
            raise GeminiServiceError("Gemini returned an incomplete question")
        expected_type = "mcq" if index < 5 else "direct"
        if question.get("type") != expected_type:
            raise GeminiServiceError("Gemini returned an invalid question type")
        if expected_type == "mcq" and len(question.get("options", [])) != 4:
            raise GeminiServiceError("Gemini returned an invalid MCQ")
    return questions


def check_answer(question, student_answer):
    prompt = f"""
Evaluate this student's answer to an interview question.
Question: {json.dumps(question, ensure_ascii=True)}
Student answer: {student_answer}
For direct questions, judge the meaning, reasoning, and concept rather than exact keywords.
Return only valid JSON with this shape:
{{
  "score": 0,
  "status": "Correct",
  "what_went_well": "...",
  "what_is_missing": "...",
  "better_answer": "...",
  "improvement_tip": "..."
}}
Score must be an integer from 0 to 10. Status must be exactly Correct, Partially Correct, or Incorrect.
"""
    return _validate_feedback(_ask_json(prompt))


def handle_dont_know(question):
    prompt = f"""
The student selected I Don't Know for this interview question:
{json.dumps(question, ensure_ascii=True)}
Give a concise, beginner-friendly explanation. Return only valid JSON with this shape:
{{
  "score": 0,
  "status": "Incorrect",
  "what_went_well": "Being honest helps an interviewer understand what to practice.",
  "what_is_missing": "...",
  "better_answer": "Include the correct answer, a simple explanation, and a small example.",
  "improvement_tip": "..."
}}
Keep the correct answer, simple explanation, small example, and interview tip inside the response fields.
"""
    return _validate_feedback(_ask_json(prompt))


def _validate_feedback(feedback):
    required = ["score", "status", "what_went_well", "what_is_missing", "better_answer", "improvement_tip"]
    if not isinstance(feedback, dict) or any(key not in feedback for key in required):
        raise GeminiServiceError("Gemini returned incomplete feedback")
    if feedback["status"] not in {"Correct", "Partially Correct", "Incorrect"}:
        raise GeminiServiceError("Gemini returned an invalid feedback status")
    try:
        feedback["score"] = max(0, min(10, int(feedback["score"])))
    except (TypeError, ValueError) as error:
        raise GeminiServiceError("Gemini returned an invalid score") from error
    return feedback


def generate_final_report(technology, level, questions, answers, results):
    prompt = f"""
Create a supportive final report for a {technology} {level} mock interview.
Questions: {json.dumps(questions, ensure_ascii=True)}
Student answers: {json.dumps(answers, ensure_ascii=True)}
Evaluation results: {json.dumps(results, ensure_ascii=True)}
Return only valid JSON with this exact shape:
{{
  "overall_score": 0,
  "mcq_score": 0,
  "direct_score": 0,
  "strong_areas": ["..."],
  "weak_areas": ["..."],
  "topics_to_improve": ["..."],
  "suggestions": ["..."],
  "encouraging_message": "..."
}}
Overall, MCQ, and direct scores must be integers from 0 to 100. MCQ and direct scores are each out of 50. Base the report on the evaluations and keep the advice specific.
"""
    report = _ask_json(prompt)
    required = ["overall_score", "mcq_score", "direct_score", "strong_areas", "weak_areas", "topics_to_improve", "suggestions", "encouraging_message"]
    if not isinstance(report, dict) or any(key not in report for key in required):
        raise GeminiServiceError("Gemini returned an incomplete final report")
    for key in ("overall_score", "mcq_score", "direct_score"):
        try:
            report[key] = max(0, min(100, int(report[key])))
        except (TypeError, ValueError) as error:
            raise GeminiServiceError("Gemini returned an invalid final score") from error
    return report
