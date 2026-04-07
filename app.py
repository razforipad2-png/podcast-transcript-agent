import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from flask import Flask, request, jsonify, send_file
from agents.manager import ManagerAgent

app = Flask(__name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")

def check_auth():
    return request.headers.get("X-API-Key") == API_SECRET_KEY

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

    agent = ManagerAgent()
    result = agent.run(input_data)

    if result["status"] == "not_found":
        return jsonify({"error": "Transcript not found"}), 404

    saved_path = result.get("saved_path")
    if not saved_path or not os.path.exists(saved_path):
        return jsonify({"error": "Transcript file not saved"}), 500

    return send_file(
        saved_path,
        as_attachment=True,
        download_name=os.path.basename(saved_path),
        mimetype="text/plain"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
