import os
import requests
import json
import re

def generate_token():
    """
    Authenticates with Salesforce using the OAuth 2.0 Password Grant Flow
    and returns the access token. Reads credentials from environment variables.
    """
    # --- Environment Variables for Salesforce Authentication ---
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    username = os.getenv('SALESFORCE_USERNAME')
    password = os.getenv('SALESFORCE_PASSWORD')
    security_token = os.getenv('SALESFORCE_SECURITY_TOKEN')
    token_url = os.getenv('TOKEN_URL')
    
    # Check for required environment variables
    if not all([client_id, client_secret, username, password, security_token, token_url]):
        raise ValueError("Missing one or more required Salesforce credential environment variables.")

    # Salesforce OAuth payload
    payload = {
        'grant_type': 'password',
        'client_id': client_id,
        'client_secret': client_secret,
        'username': username,
        'password': password + security_token  # Password is concatenated with the security token
    }
    
    print("Attempting to generate Salesforce access token...")
    
    # Get the access token
    try:
        response = requests.post(token_url, data=payload)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
        return response.json().get('access_token')
    except requests.exceptions.RequestException as e:
        print(f"Error generating token: {e}")
        # Re-raise the exception to stop the Lambda execution
        raise

def is_email(value):
    """
    Checks if a given string value has a basic email format.
    """
    if not value or not isinstance(value, str):
        return False
        
    # Simple regex for basic email structure (name@domain.tld)
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(email_regex, value) is not None

def lambda_handler(event, context):
    print("Event:", event)

    # --- ✅ Handle both direct test events and Amazon Connect invocation events ---
    details = event.get('Details', {}) or {}
    parameters = details.get('Parameters', {}) or {}
    contact_attrs = details.get('ContactData', {}).get('Attributes', {}) or {}
    # Prefer non-empty from Parameters; fall back to ContactData.Attributes; finally root (for manual tests)
    attributes = {}
    attributes.update({k: v for k, v in (event if isinstance(event, dict) else {}).items() if isinstance(v, str) and v})
    attributes.update({k: v for k, v in contact_attrs.items() if v})
    attributes.update({k: v for k, v in parameters.items() if v})
    # ---------------------------------------------------------------------------

    # The error occurs here if generate_token is not defined above
    sf_access_token = generate_token()
    sf_instance_url = os.getenv('SF_INSTANCE_URL')
    
    if not sf_instance_url:
        raise ValueError("SF_INSTANCE_URL environment variable is not set.")

    # 1. Extract and Clean Attributes
    phone_number = attributes.get('phone-number')
    house_number = attributes.get('H-No')
    
    # Safely get and strip whitespace for account/email (supports multiple keys)
    raw_account_data = (
        attributes.get('Account') or
        attributes.get('AccountOrEmail') or
        attributes.get('account_data')
    )
    account_data = raw_account_data.strip() if raw_account_data else None 

    # 2. Construct Payload based on priority
    data = None
    
    if phone_number and house_number:
        # Priority 1: Use Phone and House Number
        data = {
            "CustPhone": phone_number,
            "CustHouse": house_number
        }
        print("Using Phone and House Number for lookup.")
    elif account_data:
        # Priority 2: Use the 'Account' field
        if is_email(account_data):
            # If it looks like an email, use CustEmail
            data = {
                "CustEmail": account_data
            }
            print(f"Using Email ({account_data}) for lookup.")
        else:
            # Otherwise, treat it as a SubscriptionNumber (Account Number)
            data = {
                "SubscriptionNumber": account_data
            }
            print(f"Using Subscription Number ({account_data}) for lookup.")
    
    if data is None:
        # Keep the shape Connect expects (STRING MAP) even on error
        print("Missing required attributes: need phone-number & H-No OR Account/AccountOrEmail.")
        return {"validate": "false", "Error": "Missing required attributes"}

    # 3. Prepare and Send Salesforce API Request
    query_url = f"{sf_instance_url}/services/apexrest/customer"
    headers = {
        'Authorization': f'Bearer {sf_access_token}',
        'Content-Type': 'application/json'
    }

    print(f"Calling Salesforce API: {query_url}")
    print(f"Payload: {json.dumps(data)}")

    try:
        response = requests.post(query_url, headers=headers, data=json.dumps(data))
        response.raise_for_status() 
        response_data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling Salesforce API: {e}")
        # STRING MAP response for Connect
        return {"validate": "false", "Error": str(e)}

    print("Response Data:", response_data)

    # 4. Process Salesforce Response (STRING MAP for Connect)
    if isinstance(response_data, dict) and len(response_data) > 1:
        result = {
            "validate": "true",   # strings for Connect STRING MAP
            "CustId": response_data.get('CustId', '')
        }
    else:
        result = {
            "validate": "false",
            "CustId": ""
        }

    print("Lambda returning to Connect:", result)
    return result
