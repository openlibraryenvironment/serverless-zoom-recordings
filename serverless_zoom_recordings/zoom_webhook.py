"""
Handle a "Recording Completed" webhook from Zoom.
"""
import json
import os
import time
from base64 import b64decode

import boto3
import structlog
from botocore.exceptions import ClientError

from .util.httpapi_helpers import httpapi_response
from .util.identifiers import base64_to_uuid
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
BASE_PATH = os.environ["BASE_PATH"]
ZOOM_SECRET_TOKEN = os.environ["ZOOM_SECRET_TOKEN"]
MINIMUM_MEETING_DURATION = os.environ["MINIMUM_MEETING_DURATION"]
STEP_FUNCTION = os.environ["INGEST_ZOOM_RECORDING_STEP_MACHINE"]

stepfunction_client = boto3.client("stepfunctions")


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

    # Was the event long enough to save in the archive?
    meeting_duration = body["payload"]["object"]["duration"]
    if int(meeting_duration) < int(MINIMUM_MEETING_DURATION):
        detail = f"Recording ignored; only {meeting_duration} seconds long"
        log.warning(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode=200, body=detail)

    ##STAGE Invoke step function with recording details
    stage = "Invoke step function"
    meeting_uuid = base64_to_uuid(body["payload"]["object"]["uuid"])
    body["_recording_id"] = meeting_uuid
    unique_invocation_name = f"{meeting_uuid}-{time.time()}"

    try:
        response = stepfunction_client.start_execution(
            stateMachineArn=STEP_FUNCTION,
            name=f"{DEPLOYMENT_STAGE}-{unique_invocation_name}",
            input=json.dumps(body),
            traceHeader=aws_request_id,
        )
    except ClientError as ex:
        log.error(stage, reason=ex.response["Error"]["Code"], response=ex.response)
        return httpapi_response(
            statusCode=500,
            body=f"AWS Client Error: {ex.response['Error']['Message']}",
        )

    log.info(
        stage,
        reason="Started step function",
        response=response,
        meeting_uuid=meeting_uuid,
    )
    return httpapi_response(
        statusCode=200,
        body=f"Step function Started: {response['ResponseMetadata']['RequestId']}",
    )
