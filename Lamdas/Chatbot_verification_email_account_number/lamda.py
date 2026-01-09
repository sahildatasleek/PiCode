import json
import os
import boto3
import requests

# ───────────────
# CONFIG PLACEHOLDERS
# ───────────────
# Replace with the name of your stored secret that holds API credentials.
SECRET_NAME = "<<<your_secret_name_in_secrets_manager>>>"
# Optionally, hard-code or override these from the secret JSON
DEFAULT_API_URL = "<<<https://your-verification-api-endpoint>>>"

# ───────────────
# HELPERS
# ───────────────
def get_secret(secret_name: str):
    """Fetch credentials from AWS Secrets Manager."""
    client = boto3.client("secretsmanager")
    secret_value = client.get_secret_value(SecretId=secret_name)
    return json.loads(secret_value["SecretString"])

def verified_response():
    """Return a success message to Lex."""
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": "user_auth", "state": "Fulfilled"},
            "sessionAttributes": {"verified": "true"}
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": "Thank you! Your details are verified. Let me connect you to a specialist."
            }
        ]
    }


def ask_for_phone():
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": "phoneNumber"},
            "intent": {"name": "user_auth", "state": "InProgress"}
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": "I couldn't verify your account number. Could you please provide your phone number?"
            }
        ]
    }


def ask_for_house():
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": "houseNumber"},
            "intent": {"name": "user_auth", "state": "InProgress"}
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": "Thanks! Now please provide your house number."
            }
        ]
    }


def ask_for_account_number_again():
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": "accountNumber"},
            "intent": {"name": "user_auth", "state": "InProgress"}
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": "Sorry, I couldn’t verify your details. Can you please re-enter your subscription/account number?"
            }
        ]
    }


# ───────────────
# MAIN HANDLER
# ───────────────
def lambda_handler(event, context):
    try:
        print("Incoming event:", json.dumps(event))
        slots = event["sessionState"]["intent"].get("slots", {})

        # Extract slots
        account_number = slots.get("accountNumber", {}).get("value", {}).get("interpretedValue")
        phone_number = slots.get("phoneNumber", {}).get("value", {}).get("interpretedValue")
        house_number = slots.get("houseNumber", {}).get("value", {}).get("interpretedValue")

        # Load secrets
        secret = get_secret(SECRET_NAME)
        api_url = secret.get("api_url", DEFAULT_API_URL)
        token = secret.get("api_token")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # ───────────────────────────────────────────────
        # 1️⃣ FIRST ATTEMPT — Lookup using Subscription Number
        # ───────────────────────────────────────────────
        if account_number:
            payload = {"SubscriptionNumber": account_number}

            print("PRIMARY lookup payload:", payload)
            response = requests.post(api_url, headers=headers, json=payload, timeout=5)
            data = response.json()
            print("PRIMARY lookup response:", data)

            # Match found
            if isinstance(data, dict) and data.get("CustId"):
                return verified_response()

            # Not found → ask for phone number
            return ask_for_phone()

        # ───────────────────────────────────────────────
        # 2️⃣ User provided phone number but not house
        # ───────────────────────────────────────────────
        if phone_number and not house_number:
            return ask_for_house()

        # ───────────────────────────────────────────────
        # 3️⃣ SECOND ATTEMPT — Lookup using phone + house
        # ───────────────────────────────────────────────
        if phone_number and house_number:
            payload = {
                "CustPhone": phone_number,
                "CustHouse": house_number
            }

            print("SECONDARY lookup payload:", payload)
            response = requests.post(api_url, headers=headers, json=payload, timeout=5)
            data = response.json()
            print("SECONDARY lookup response:", data)

            # Match found
            if isinstance(data, dict) and data.get("CustId"):
                return verified_response()

            # Still not found → start over
            return ask_for_account_number_again()

        # ───────────────────────────────────────────────
        # No slot data yet → ask for account number
        # ───────────────────────────────────────────────
        return ask_for_account_number_again()

    except Exception as e:
        print("Exception:", e)
        return ask_for_account_number_again()
