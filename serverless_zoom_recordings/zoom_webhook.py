"""
Handle a "Recording Completed" webhook from Zoom.

If the webhook has the correct metadata, call the `invoke_stepfunction` lambda.
"""
import json
import os
from base64 import b64decode

import boto3
import structlog

from .util.httpapi_helpers import httpapi_response
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
BASE_PATH = os.environ["BASE_PATH"]
ZOOM_SECRET_TOKEN = os.environ["ZOOM_SECRET_TOKEN"]
INVOKE_STEPFUNCTION_ARN = os.environ["INVOKE_STEPFUNCTION_ARN"]

lambda_client = boto3.client("lambda")


def handler(event, context):
    """Handle Zoom recording completed webhook event"""
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = "*NO CONTEXT*"
    if context is not None:
        aws_request_id = context.aws_request_id

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    log.info("STARTED", httpapi_event=event)

    ##STAGE Validate webhook content
    stage = "Validate webhook content"

    # Did we get the anticipated authorization header value?
    for autho_header in event["headers"]["authorization"].split(","):
        if autho_header == ZOOM_SECRET_TOKEN:
            break
    else:
        detail = "Invalid authorization token received"
        log.error(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode="401", body=detail)

    # Did we get POSTed content?
    if "body" in event and "event" in event["body"]:
        body = event["body"]
    else:
        detail = "Invalid Zoom POST content received"
        log.error(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode="400", body=detail)

    # Un-Base64-Encode
    if "isBase64Encoded" in event and event["isBase64Encoded"]:
        body = b64decode(body)
    body = json.loads(event["body"])
    log.debug(stage, reason="Parsed Zoom webhook", body=body)

    # Did we get a recording completed event?
    if body["event"] != "recording.completed":
        detail = f"Received unexpected '{body['event']}' event"
        log.error(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode=400, body=detail)

    ## STAGE Call invoke_stepfunction lambda
    stage = "Call invoke_stepfunction lambda"

    log.debug(
        stage,
        reason="Calling lambda",
        detail={"FunctionName": INVOKE_STEPFUNCTION_ARN},
        body=body,
    )
    lambda_response = lambda_client.invoke(
        FunctionName=INVOKE_STEPFUNCTION_ARN,
        InvocationType="RequestResponse",
        LogType="Tail",
        Payload=json.dumps(body),
    )
    log.info(stage, reason="Call completed", detail=lambda_response)
