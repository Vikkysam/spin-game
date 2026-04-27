import os
import time
import re
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

load_dotenv()

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

# @app.route("/")
# def home():
#     return {"message": "Backend is running"}

# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 5000))
#     app.run(host="0.0.0.0", port=port)

PORT = 3000
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()

# Demo memory store
users = {}


# @app.route("/")
# def serve_index():
#     return send_from_directory("public", "index.html")


# @app.route("/game")
# def serve_game():
#     return send_from_directory("public", "game.html")

@app.route("/")
def home():
    return jsonify({"message": "Backend is running"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/banks", methods=["GET"])
def get_banks():
    if not PAYSTACK_SECRET_KEY:
        return jsonify({
            "success": False,
            "message": "Missing PAYSTACK_SECRET_KEY in environment or .env file."
        }), 500

    try:
        response = requests.get(
            "https://api.paystack.co/bank",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            params={
                "country": "nigeria"
            },
            timeout=20
        )

        paystack_data = response.json()

        if response.status_code != 200 or not paystack_data.get("status"):
            return jsonify({
                "success": False,
                "message": paystack_data.get("message", "Could not fetch banks.")
            }), response.status_code if response.status_code else 400

        banks = []
        for bank in paystack_data.get("data", []):
            if bank.get("active", True):
                banks.append({
                    "name": bank.get("name", ""),
                    "code": str(bank.get("code", "")).strip()
                })

        banks.sort(key=lambda item: item["name"].lower())

        return jsonify({
            "success": True,
            "banks": banks
        }), 200

    except Exception as error:
        print("banks error:", str(error))
        return jsonify({
            "success": False,
            "message": "Something went wrong while fetching banks."
        }), 500


@app.route("/verify-account", methods=["POST"])
def verify_account():
    data = request.get_json(silent=True) or {}

    bank_code = str(data.get("bankCode", "")).strip()
    account_number = str(data.get("accountNumber", "")).strip()

    if not bank_code:
        return jsonify({
            "verified": False,
            "message": "Please select a bank."
        }), 400

    if not re.fullmatch(r"\d{10}", account_number):
        return jsonify({
            "verified": False,
            "message": "Account number must be exactly 10 digits."
        }), 400

    if not PAYSTACK_SECRET_KEY:
        return jsonify({
            "verified": False,
            "message": "Missing PAYSTACK_SECRET_KEY in environment or .env file."
        }), 500

    try:
        response = requests.get(
            "https://api.paystack.co/bank/resolve",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json"
            },
            params={
                "account_number": account_number,
                "bank_code": bank_code
            },
            timeout=20
        )

        paystack_data = response.json()

        if response.status_code != 200 or not paystack_data.get("status"):
            return jsonify({
                "verified": False,
                "message": paystack_data.get(
                    "message",
                    "Could not resolve account. Check the bank and account number."
                )
            }), response.status_code if response.status_code else 400

        resolved = paystack_data.get("data", {})

        return jsonify({
            "verified": True,
            "accountName": resolved.get("account_name", ""),
            "accountNumber": resolved.get("account_number", account_number),
            "bankCode": bank_code
        }), 200

    except Exception as error:
        print("verify-account error:", str(error))
        return jsonify({
            "verified": False,
            "message": "Something went wrong during account verification."
        }), 500


@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.get_json(silent=True) or {}
    reference = data.get("reference")

    if not reference:
        return jsonify({"error": "Missing payment reference"}), 400

    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            timeout=15
        )

        paystack_data = response.json()
        tx = paystack_data.get("data")

        if not tx or tx.get("status") != "success":
            return jsonify({
                "success": False,
                "error": "Payment not successful"
            }), 400

        # amount 50000 = ₦500.00 in kobo
        if tx.get("amount") != 50000 or tx.get("currency") != "NGN":
            return jsonify({
                "success": False,
                "error": "Invalid payment amount or currency"
            }), 400

        if reference not in users:
            users[reference] = {
                "paid": True,
                "paidSpinUsed": False,
                "shareCount": 0,
                "freeSpinAvailable": False,
                "freeSpinUsed": False,
                "createdAt": int(time.time() * 1000)
            }
        else:
            users[reference]["paid"] = True

        return jsonify({"success": True})

    except Exception as error:
        print("verify-payment error:", str(error))
        return jsonify({"error": "Verification failed"}), 500


@app.route("/check-access", methods=["POST"])
def check_access():
    data = request.get_json(silent=True) or {}
    reference = data.get("reference")

    if not reference or reference not in users:
        return jsonify({
            "allowed": False,
            "paidSpinAvailable": False,
            "freeSpinAvailable": False
        })

    user = users[reference]
    paid_spin_available = user["paid"] and not user["paidSpinUsed"]
    free_spin_available = user["freeSpinAvailable"] and not user["freeSpinUsed"]

    return jsonify({
        "allowed": paid_spin_available or free_spin_available,
        "paidSpinAvailable": paid_spin_available,
        "freeSpinAvailable": free_spin_available
    })


@app.route("/share-action", methods=["POST"])
def share_action():
    data = request.get_json(silent=True) or {}
    reference = data.get("reference")
    user = users.get(reference)

    if not reference or not user:
        return jsonify({"error": "Invalid reference"}), 400

    if not user["paid"]:
        return jsonify({
            "error": "First payment required before share reward"
        }), 403

    if user["freeSpinAvailable"] and not user["freeSpinUsed"]:
        return jsonify({
            "success": True,
            "shareCount": user["shareCount"],
            "freeSpinAvailable": True,
            "freeSpinUsed": False,
            "message": "Free spin already unlocked"
        })

    user["shareCount"] += 1

    if user["shareCount"] >= 5:
        user["freeSpinAvailable"] = True

    return jsonify({
        "success": True,
        "shareCount": user["shareCount"],
        "freeSpinAvailable": user["freeSpinAvailable"],
        "freeSpinUsed": user["freeSpinUsed"]
    })


@app.route("/share-status", methods=["POST"])
def share_status():
    data = request.get_json(silent=True) or {}
    reference = data.get("reference")
    user = users.get(reference)

    if not reference or not user:
        return jsonify({
            "shareCount": 0,
            "freeSpinAvailable": False,
            "freeSpinUsed": False
        })

    return jsonify({
        "shareCount": user.get("shareCount", 0),
        "freeSpinAvailable": bool(user.get("freeSpinAvailable")),
        "freeSpinUsed": bool(user.get("freeSpinUsed"))
    })


@app.route("/spin", methods=["POST"])
def spin():
    data = request.get_json(silent=True) or {}
    reference = data.get("reference")
    user = users.get(reference)

    if not user:
        return jsonify({"error": "User not found"}), 403

    has_paid_spin = user["paid"] and not user["paidSpinUsed"]
    has_free_spin = user["freeSpinAvailable"] and not user["freeSpinUsed"]

    if not has_paid_spin and not has_free_spin:
        return jsonify({"error": "No available spin"}), 403

    if has_paid_spin:
        user["paidSpinUsed"] = True
    else:
        user["freeSpinUsed"] = True

    return jsonify({
        "result": "try_again",
        "label": "TRY AGAIN",
        "angle": 195
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)