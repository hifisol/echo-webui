from flask import Blueprint, render_template, request, jsonify, current_app

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


@bp.route("/")
def index():
    runner = current_app.config["task_runner"]
    jobs = runner.list_jobs()
    return render_template("jobs/index.html", jobs=jobs)


@bp.route("/api/list")
def job_list():
    runner = current_app.config["task_runner"]
    status = request.args.get("status")
    jobs = runner.list_jobs(status=status)
    return render_template("jobs/_job_list.html", jobs=jobs)


@bp.route("/api/<job_id>")
def job_detail(job_id):
    runner = current_app.config["task_runner"]
    job = runner.get_job(job_id)
    if not job:
        return "Job not found", 404
    return render_template("jobs/_log_viewer.html", job=job)


@bp.route("/api/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    runner = current_app.config["task_runner"]
    if runner.cancel(job_id):
        return render_template("jobs/_job_list.html", jobs=runner.list_jobs())
    return "Job not found or not running", 404
