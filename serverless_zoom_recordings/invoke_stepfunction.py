"""
Given a Zoom recording event, start the Step Function
"""
import json
import os
import time

import boto3
import structlog
from botocore.exceptions import ClientError
from zoomus import ZoomClient

from .util.httpapi_helpers import httpapi_response
from .util.identifiers import base64_to_uuid
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
BASE_PATH = os.environ["BASE_PATH"]
MINIMUM_MEETING_DURATION = os.environ["MINIMUM_MEETING_DURATION"]
ZOOM_API_KEY = os.environ["ZOOM_API_KEY"]
ZOOM_API_SECRET = os.environ["ZOOM_API_SECRET"]
STEP_FUNCTION = os.environ["INGEST_ZOOM_RECORDING_STEP_MACHINE"]

stepfunction_client = boto3.client("stepfunctions")
zoom_client = ZoomClient(ZOOM_API_KEY, ZOOM_API_SECRET)


def handler(event, context):
    """Handle Zoom recording completed webhook event"""
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = "*NO CONTEXT*"
    if context is not None:
        aws_request_id = context.aws_request_id

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    log.info("STARTED", detail=event)

    ## STAGE Invoke step function with recording details
    stage = "Invoke step function"
    log.debug(stage, reason="Zoom recording info", detail=event)

    # Was the event long enough to save in the archive?
    meeting_duration = event["payload"]["object"]["duration"]
    if int(meeting_duration) < int(MINIMUM_MEETING_DURATION):
        detail = f"Recording ignored; only {meeting_duration} minutes long"
        log.warning(stage, reason="POST rejected", detail=detail)
        return httpapi_response(statusCode=200, body=detail)

    # Events invoked directly to `invoke_stepfunction` may not have a Zoom
    # JWT, so we get one.
    if "download_token" not in event:
        event["download_token"] = zoom_client.config["token"]

    ##STAGE Invoke step function with recording details
    stage = "Invoke step function"
    meeting_uuid = base64_to_uuid(event["payload"]["object"]["uuid"])
    event["_recording_id"] = meeting_uuid
    unique_invocation_name = f"{meeting_uuid}-{time.time()}"

    try:
        response = stepfunction_client.start_execution(
            stateMachineArn=STEP_FUNCTION,
            name=f"{DEPLOYMENT_STAGE}-{unique_invocation_name}",
            input=json.dumps(event),
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
