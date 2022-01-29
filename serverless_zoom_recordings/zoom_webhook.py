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
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
BASE_PATH = os.environ["BASE_PATH"]
ZOOM_SECRET_TOKEN = os.environ["ZOOM_SECRET_TOKEN"]
MINIMUM_MEETING_DURATION = os.environ["MINIMUM_MEETING_DURATION"]
STEP_FUNCTION = os.environ["INGEST_ZOOM_RECORDING_STEP_MACHINE"]

stepfunction_client = boto3.client("stepfunctions")


def handler(event, context):
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = "*NO CONTEXT*"
    if context is not None:
        aws_request_id = context.aws_request_id

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    log.info("STARTED", httpapi_event=event)

    # Did we get the anticipated authorization header value?
    for autho_header in event["headers"]["authorization"].split(","):
        if autho_header == ZOOM_SECRET_TOKEN:
            break
    else:
        reason = "Invalid authorization token received"
        log.error("POST rejected", reason=reason)
        return httpapi_response(statusCode="401", body=reason)

    # Did we get POSTed content?
    if "body" in event and "event" in event["body"]:
        body = event["body"]
    else:
        reason = "Invalid Zoom POST content received"
        log.error("POST rejected", reason=reason)
        return httpapi_response(statusCode="400", body=reason)

    # Un-Base64-Encode
    if "isBase64Encoded" in event and event["isBase64Encoded"]:
        body = b64decode(body)
    body = json.loads(event["body"])
    log.debug("Parsed Zoom event", body=body)

    # Did we get a recording completed event?
    if body["event"] != "recording.completed":
        reason = f"Received unexpected '{body['event']}' event"
        log.error("POST rejected", reason=reason)
        return httpapi_response(statusCode=400, body=reason)

    # Was the event long enough to save in the archive?
    meeting_duration = body["payload"]["object"]["duration"]
    if int(meeting_duration) < int(MINIMUM_MEETING_DURATION):
        reason = f"Recording ignored; only {meeting_duration} seconds long"
        log.warning("POST rejected", reason=reason)
        return httpapi_response(statusCode=200, body=reason)

    # Push body to queue. 'meeting_uuid' used as a deduplication key
    meeting_uuid = body["payload"]["object"]["uuid"]
    if DEPLOYMENT_STAGE == "dev":
        meeting_uuid = f"{meeting_uuid}-DEV-{time.time()}"

    try:
        response = stepfunction_client.start_execution(
            stateMachineArn=STEP_FUNCTION,
            name=f"{DEPLOYMENT_STAGE}-{meeting_uuid}",
            input=json.dumps(body),
            traceHeader=aws_request_id,
        )
    except ClientError as e:
        log.error(
            "AWS Client Error",
            reason=e.response["Error"]["Code"],
            response=e.response,
        )
        return httpapi_response(
            statusCode=500,
            body=f"AWS Client Error: {e.response['Error']['Message']}",
        )

    log.info(
        "Stepfunction Started",
        reason=response["ResponseMetadata"]["RequestId"],
        response=response,
        meeting_uuid=meeting_uuid,
    )
    return httpapi_response(
        statusCode=200,
        body=f"Stepfunction Started: {response['ResponseMetadata']['RequestId']}",
    )
