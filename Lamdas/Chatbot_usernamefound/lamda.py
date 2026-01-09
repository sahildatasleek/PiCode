import json

def lambda_handler(event, context):

    # Amazon Connect attributes safely extract
    attributes = event.get("Details", {}).get("ContactData", {}).get("Attributes", {})

    # Name value check
    name_value = attributes.get("customerName", "")

    # True/False response
    if name_value and name_value.strip():
        return {
            "name_found": "True",
            "name_value": name_value
        }
    else:
        return {
            "name_found": "False",
            "name_value": ""
        }