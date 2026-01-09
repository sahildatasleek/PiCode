import json
import boto3
import os
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr
from collections import Counter
from datetime import datetime, timedelta

dynamodb = boto3.resource('dynamodb')

# FIX 1: Retrieve the table name and use .strip() to remove any leading or trailing whitespace.
try:
    TABLE_NAME = os.environ['Table'].strip()
    table = dynamodb.Table(TABLE_NAME)
except KeyError:
    # Handle case where environment variable 'Table' is not set
    # Note: In a real Lambda, this should be configured correctly.
    print("Error: 'Table' environment variable is not set.")
    table = None # Initialize table to None if env var is missing

# Function to calculate percentage using a specific denominator (total_participants)
def calculate_percentage_by_participant(values, total_participants):
    if not values or total_participants == 0:
        return {}
    
    counter = Counter(values)
    
    # Calculate percentage based on the specific total_participants provided
    return {k: round((v / total_participants) * 100, 2) for k, v in counter.items()}

# Helper function for robust boolean check (handles bool True and string "True")
def is_chatbot_true(item):
    chatbot_value = item.get('ChatBot')
    if isinstance(chatbot_value, bool):
        return chatbot_value is True
    if isinstance(chatbot_value, str):
        return chatbot_value.upper() == 'TRUE'
    return False


def lambda_handler(event, context):
    print("event", event)

    if table is None:
         return {
             "statusCode": 500,
             # Ensure response body is a JSON string
             "body": json.dumps({"error": "DynamoDB table connection failed. 'Table' environment variable is missing or invalid."})
         }
    
    # === CRITICAL FIX: Access start/end directly from the root event object ===
    # This matches the expected input structure from your API Gateway Mapping Template (Non-Proxy).
    start_timestamp = event.get('start')
    end_timestamp = event.get('end')

    if not start_timestamp or not end_timestamp:
        return {
            "statusCode": 400,
            # Ensure response body is a JSON string
            "body": json.dumps({"error": "Missing required keys: 'start' and 'end' must be provided in the event payload."})
        }

    # Adjust end date to include full day
    try:
        end_date_obj = datetime.strptime(end_timestamp, "%Y-%m-%d")
        end_date_obj += timedelta(days=1)
        end_timestamp = end_date_obj.strftime("%Y-%m-%d")
        print("Adjusted end timestamp:", end_timestamp)
    except ValueError as ve:
        return {
            "statusCode": 400,
            # Ensure response body is a JSON string
            "body": json.dumps({"error": f"Invalid date format for 'end'. Expected 'YYYY-MM-DD'. Details: {str(ve)}"})
        }

    try:
        # --- 1. Initial Scan to get all items in the date range ---
        time_fe = Attr('InitiationTimestamp').between(start_timestamp, end_timestamp)
        
        # Best Practice: Only fetch the attributes we need
        projection_expression = "InitiationTimestamp, ChannelType, ChatBot, Q1, Q2, Q3, Q4, Q5, Q6"

        response = table.scan(
            FilterExpression=time_fe,
            ProjectionExpression=projection_expression
        )
        items = response['Items']

        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=time_fe,
                ProjectionExpression=projection_expression,
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response['Items'])

        total_calls = len(items)
        
        # --- 2. Filter items: Only include records where ChannelType is CHAT AND ChatBot is True/\"True\" ---
        filtered_items = [
            item for item in items 
            if item.get('ChannelType', '').upper() == 'CHAT' and is_chatbot_true(item)
        ]

        # The count of records that meet BOTH criteria: This is our denominator.
        chat_chatbot_count = len(filtered_items) 
        
        # Question containers - All Q1-Q6 are included now
        survey_counts = {'Q1': [], 'Q2': [], 'Q3': [], 'Q4': [], 'Q5': [], 'Q6': []}

        # Questions processed for CHAT
        chat_questions = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6']

        for item in filtered_items:
            for q in chat_questions:
                # Append only if the key exists AND has a non-empty/non-None value
                if q in item and item.get(q) is not None and item.get(q) != '':
                    survey_counts[q].append(item[q])

        # The output format will be a list containing a single dictionary
        result = [
            {
                "Total_Calls": total_calls, 
                "Survey_Participated": f"Chat : {chat_chatbot_count}",
                "Question_Averages": {
                    "Q1": calculate_percentage_by_participant(survey_counts["Q1"], chat_chatbot_count),
                    "Q2": calculate_percentage_by_participant(survey_counts["Q2"], chat_chatbot_count),
                    "Q3": calculate_percentage_by_participant(survey_counts["Q3"], chat_chatbot_count),
                    "Q4": calculate_percentage_by_participant(survey_counts["Q4"], chat_chatbot_count),
                    "Q5": calculate_percentage_by_participant(survey_counts["Q5"], chat_chatbot_count),
                    "Q6": calculate_percentage_by_participant(survey_counts["Q6"], chat_chatbot_count)
                }
            }
        ]

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": result # 'result' is the Python list/dictionary
        }

    except ClientError as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            # Ensure error body is a JSON string
            "body": json.dumps({"error": str(e)})
        }