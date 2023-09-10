"""
Handle a "Recording Completed" webhook from Zoom.

If the webhook has the correct metadata, call the `invoke_stepfunction` lambda.
"""
import hashlib
import hmac
import json
import os
from base64 import b64decode

import boto3
import structlog

from .util.httpapi_helpers import httpapi_response
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
BASE_PATH = os.environ["BASE_PATH"]
ZOOM_WEBHOOK_SECRET_TOKEN = os.environ["ZOOM_WEBHOOK_SECRET_TOKEN"]
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

    # Did we get the anticipated Zoom Webhook headers?
    zm_request_timestamp = event["headers"].get("x-zm-request-timestamp", None)
    if not zm_request_timestamp:
        detail = "Required x-zm-request-timestamp HTTP header not received"
        log.error(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode="401", body=detail)

    zm_signature = event["headers"].get("x-zm-signature", None)
    if not zm_signature:
        detail = "Required x-zm-signature HTTP header not received"
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

    # Is this a valid webhook from Zoom?
    zoom_message = f"v0:{zm_request_timestamp}:{event['body']}"
    zoom_message_hash = hmac.new(
        ZOOM_WEBHOOK_SECRET_TOKEN.encode("utf-8"),
        zoom_message.encode("utf-8"),
        hashlib.sha256,
    )
    zoom_message_hex_digest = zoom_message_hash.hexdigest()
    if zm_signature != f"v0={zoom_message_hex_digest}":
        detail = f"Computed hash does not match: {zm_signature=} and {zoom_message_hex_digest=} for {zoom_message=}"
        log.error(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode="401", body=detail)

    # Did we get a Zoom webhook endpoint validation request?
    if body["event"] == "endpoint.url_validation":
        zoom_plain_token = body["payload"]["plainToken"]
        zoom_token_hash = hmac.new(
            ZOOM_WEBHOOK_SECRET_TOKEN.encode("utf-8"),
            zoom_plain_token.encode("utf-8"),
            hashlib.sha256,
        )
        zoom_token_hex_digest = zoom_token_hash.hexdigest()
        validation_response = {
            "plainToken": zoom_plain_token,
            "encryptedToken": zoom_token_hex_digest,
        }
        validation_response_json = json.dumps(validation_response)
        detail = "Returning Webhook validation JSON"
        log.info(stage, reason="Validation sent", detail=validation_response_json)
        return httpapi_response(statusCode="200", body=validation_response_json)

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
