import os
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

from gemini_service import (
    GeminiServiceError,
    check_answer,
    generate_final_report,
    generate_questions,
    handle_dont_know,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-development-secret")

TECHNOLOGIES = ["Python", "Java", "C", "n8n", "AI Automation"]
LEVELS = ["Basic", "Intermediate", "Advanced"]


def interview_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "questions" not in session:
            flash("Start an interview before opening that page.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped_view


@app.get("/")
def index():
    return render_template("index.html", technologies=TECHNOLOGIES)


@app.post("/select-technology")
def select_technology():
    technology = request.form.get("technology", "").strip()
    if technology not in TECHNOLOGIES:
        flash("Please choose one technology to continue.", "error")
        return redirect(url_for("index"))

    session.clear()
    session["technology"] = technology
    return redirect(url_for("level"))


@app.get("/level")
def level():
    if "technology" not in session:
        return redirect(url_for("index"))
    return render_template("level.html", technology=session["technology"], levels=LEVELS)


@app.post("/select-level")
def select_level():
    level_name = request.form.get("level", "").strip()
    if level_name not in LEVELS or "technology" not in session:
        flash("Please choose a valid knowledge level.", "error")
        return redirect(url_for("level"))

    session["level"] = level_name
    return redirect(url_for("start_interview"))


@app.get("/start-interview")
def start_interview():
    if "technology" not in session or "level" not in session:
        return redirect(url_for("index"))

    try:
        questions = generate_questions(session["technology"], session["level"])
    except GeminiServiceError as error:
        print(f"Gemini error while generating questions: {error}")
        flash("Gemini could not create the interview right now. Please check your API key and try again.", "error")
        return redirect(url_for("index"))

    session["questions"] = questions
    session["current_question"] = 0
    session["answers"] = []
    session["results"] = []
    session.pop("feedback", None)
    return redirect(url_for("interview"))


@app.get("/interview")
@interview_required
def interview():
    question_index = session.get("current_question", 0)
    if question_index >= len(session["questions"]):
        return redirect(url_for("result"))

    return render_template(
        "interview.html",
        question=session["questions"][question_index],
        question_index=question_index,
        total=len(session["questions"]),
        technology=session["technology"],
        level=session["level"],
    )


@app.post("/submit-answer")
@interview_required
def submit_answer():
    question_index = session.get("current_question", 0)
    questions = session["questions"]
    if question_index >= len(questions):
        return redirect(url_for("result"))

    question = questions[question_index]
    answer = request.form.get("answer", "").strip()
    if not answer:
        flash("Please answer the question or use I Don't Know.", "error")
        return redirect(url_for("interview"))

    try:
        if _is_dont_know_answer(answer):
            feedback = handle_dont_know(question)
            answer = "I don't know"
        else:
            feedback = check_answer(question, answer)
    except GeminiServiceError as error:
        print(f"Gemini error while checking answer: {error}")
        flash("Gemini could not evaluate that answer. Please try again.", "error")
        return redirect(url_for("interview"))

    _store_result(answer, feedback)
    session["feedback"] = feedback
    return redirect(url_for("feedback"))


def _is_dont_know_answer(answer):
    normalized_answer = " ".join(answer.casefold().replace("’", "'").split())
    return normalized_answer in {
        "i don't know",
        "i don't know the answer",
        "not sure",
        "i am not sure",
        "no idea",
    }


@app.post("/dont-know")
@interview_required
def dont_know():
    question_index = session.get("current_question", 0)
    questions = session["questions"]
    if question_index >= len(questions):
        return redirect(url_for("result"))

    try:
        feedback = handle_dont_know(questions[question_index])
    except GeminiServiceError as error:
        print(f"Gemini error while explaining answer: {error}")
        flash("Gemini could not prepare the explanation. Please try again.", "error")
        return redirect(url_for("interview"))

    _store_result("I don't know", feedback)
    session["feedback"] = feedback
    return redirect(url_for("feedback"))


def _store_result(answer, feedback):
    answers = session.get("answers", [])
    results = session.get("results", [])
    answers.append(answer)
    results.append(feedback)
    session["answers"] = answers
    session["results"] = results


@app.get("/feedback")
@interview_required
def feedback():
    if "feedback" not in session:
        return redirect(url_for("interview"))

    question_index = session.get("current_question", 0)
    return render_template(
        "feedback.html",
        feedback=session["feedback"],
        question_index=question_index,
        total=len(session["questions"]),
        is_last=question_index == len(session["questions"]) - 1,
    )


@app.post("/next-question")
@interview_required
def next_question():
    next_index = session.get("current_question", 0) + 1
    session["current_question"] = next_index
    session.pop("feedback", None)

    if next_index >= len(session["questions"]):
        return redirect(url_for("result"))
    return redirect(url_for("interview"))


@app.get("/result")
@interview_required
def result():
    if len(session.get("results", [])) < len(session["questions"]):
        return redirect(url_for("interview"))

    if "final_report" not in session:
        try:
            session["final_report"] = generate_final_report(
                session["technology"], session["level"], session["questions"], session["answers"], session["results"]
            )
        except GeminiServiceError as error:
            print(f"Gemini error while creating final report: {error}")
            flash("The interview is complete, but Gemini could not create the final report.", "error")
            return redirect(url_for("index"))

    return render_template(
        "result.html",
        report=session["final_report"],
        technology=session["technology"],
        level=session["level"],
        questions=session["questions"],
        answers=session["answers"],
        results=session["results"],
    )


if __name__ == "__main__":
    app.run(debug=True)
