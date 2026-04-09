import os
import sys
import uuid
import threading
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from agents.manager import ManagerAgent

app = Flask(__name__)
CORS(app)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")

# In-memory job store: job_id -> {status, saved_path, error}
jobs = {}

def check_auth():
    incoming = request.headers.get("X-API-Key", "")
    return incoming == API_SECRET_KEY

def run_job(job_id, input_data):
    try:
        agent = ManagerAgent()
        result = agent.run(input_data)
        if result["status"] == "not_found":
            jobs[job_id] = {"status": "not_found", "saved_path": None, "error": "Transcript not found"}
        elif not result.get("saved_path") or not os.path.exists(result["saved_path"]):
            jobs[job_id] = {"status": "error", "saved_path": None, "error": "Transcript file not saved"}
        else:
            jobs[job_id] = {"status": "done", "saved_path": result["saved_path"], "error": None}
    except Exception as e:
        jobs[job_id] = {"status": "error", "saved_path": None, "error": str(e)}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/transcribe", methods=["POST"])
def transcribe():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    if "url" in data:
        input_data = {"mode": "url", "url": data["url"]}
    elif "show" in data and "episode" in data:
        input_data = {"mode": "search", "show": data["show"], "episode": data["episode"]}
    else:
        return jsonify({"error": "Provide either 'url' or 'show'+'episode'"}), 400
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "saved_path": None, "error": None}
    thread = threading.Thread(target=run_job, args=(job_id, input_data))
    thread.daemon = True
    thread.start()
    return jsonify({"job_id": job_id}), 202

@app.route("/status/<job_id>", methods=["GET"])
def status(job_id):
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route("/result/<job_id>", methods=["GET"])
def result(job_id):
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] != "done":
        return jsonify({"error": "Job not complete"}), 400
    saved_path = job["saved_path"]
    if not saved_path or not os.path.exists(saved_path):
        return jsonify({"error": "File not found"}), 500
    return send_file(
        saved_path,
        as_attachment=True,
        download_name=os.path.basename(saved_path),
        mimetype="text/plain"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
