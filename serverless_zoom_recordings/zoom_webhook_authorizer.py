"""
Handle a "Recording Completed" webhook from Zoom.
"""
import os

ZOOM_SECRET_TOKEN = os.environ["ZOOM_SECRET_TOKEN"]


def handler(event, _context):
    print(f"Method ARN: {event['methodArn']}")

    # Did we get the anticipated authorization header value?
    for autho_header in event["authorizationToken"].split(","):
        if autho_header == ZOOM_SECRET_TOKEN:
            break
    else:
        print(f"Got invalid authorization token: {event['authorizationToken']}")
        raise Exception("Unauthorized")

    return {
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Resource": [event["methodArn"]],
                    "Effect": "Allow",
                }
            ],
        },
        "principalId": "ZoomWebhookAuthorizer",
    }
