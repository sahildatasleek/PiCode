import os
import json
import urllib.request
import urllib.error
import urllib.parse


def lambda_handler(event, context):
    print("Event Received:", json.dumps(event, indent=4))

    # Generate Salesforce Access Token
    sf_access_token = generate_token()
    sf_instance_url = os.getenv('SF_INSTANCE_URL')

    # Extract attributes from event
    attributes = event.get('Details', {}).get('ContactData', {}).get('Attributes', {})
    phone_number = attributes.get('phone-number')
    house_number = attributes.get('H-No')
    account_number = event.get('Account')
    email = event.get('Email')

    # Construct payload
    if account_number:
        data = {"SubscriptionNumber": account_number}
    else:
        raise KeyError("Missing required attribute: 'Account'")

    # Salesforce endpoint
    query_url = f"{sf_instance_url}/services/apexrest/customer"
    headers = {
        'Authorization': f'Bearer {sf_access_token}',
        'Content-Type': 'application/json'
    }

    try:
        # Call Salesforce API
        response_data = make_post_request(query_url, headers, data)

        # ALWAYS PRINT FULL RESPONSE
        print("\n========== FULL SALESFORCE RESPONSE ==========")
        print(json.dumps(response_data, indent=4))
        print("==============================================\n")

        # -------- Validation Logic --------
        if isinstance(response_data, dict) and response_data.get('CustId'):
            return {
                "validate": "true",
                "CustId": response_data['CustId'],
                "Name": response_data.get('FirstName'),
                "Email": response_data.get('Email')
            }

        elif isinstance(response_data, list) and len(response_data) > 0:
            return {
                "validate": "true",
                "CustId": response_data[0].get('CustId'),
                "Name": response_data[0].get('FirstName'),
                "Email": response_data[0].get('Email')
            }

        else:
            return {"validate": "false"}

    except Exception as e:
        print("Error communicating with Salesforce:", str(e))
        return {"validate": "false", "error": str(e)}


def generate_token():
    """Generate Salesforce OAuth access token."""
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    username = os.getenv('SALESFORCE_USERNAME')
    password = os.getenv('SALESFORCE_PASSWORD')
    security_token = os.getenv('SALESFORCE_SECURITY_TOKEN')
    token_url = os.getenv('TOKEN_URL')

    payload = {
        'grant_type': 'password',
        'client_id': client_id,
        'client_secret': client_secret,
        'username': username,
        'password': password + security_token
    }

    try:
        response_data = make_post_request(token_url, {}, payload, form_encoded=True)

        # ALWAYS PRINT FULL TOKEN RESPONSE
        print("\n========== SALESFORCE TOKEN RESPONSE ==========")
        print(json.dumps(response_data, indent=4))
        print("===============================================\n")

        access_token = response_data.get('access_token')
        if not access_token:
            raise ValueError(f"Failed to obtain access token: {response_data}")

        return access_token

    except Exception as e:
        print("Token generation failed:", str(e))
        raise


def make_post_request(url, headers, payload, form_encoded=False):
    """Helper to send POST requests using urllib."""
    if form_encoded:
        # Salesforce token request
        data = urllib.parse.urlencode(payload).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        # Salesforce REST API request
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            response_body = response.read().decode('utf-8')
            return json.loads(response_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"HTTPError {e.code}: {error_body}")
        raise
    except urllib.error.URLError as e:
        print(f"URLError: {e.reason}")
        raise
