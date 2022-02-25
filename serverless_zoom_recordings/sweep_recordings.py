"""
Ingest metadata into S3 and DynamoDB
"""
import json
import os
import time
from datetime import datetime

import boto3
import structlog
from botocore.exceptions import ClientError
from dateutil.relativedelta import relativedelta
from zoomus import ZoomClient

from .util.identifiers import base64_to_uuid
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
ZOOM_API_KEY = os.environ["ZOOM_API_KEY"]
ZOOM_API_SECRET = os.environ["ZOOM_API_SECRET"]
MINIMUM_MEETING_DURATION = os.environ["MINIMUM_MEETING_DURATION"]
STEP_FUNCTION = os.environ["INGEST_ZOOM_RECORDING_STEP_MACHINE"]


zoom_client = ZoomClient(ZOOM_API_KEY, ZOOM_API_SECRET)
stepfunction_client = boto3.client("stepfunctions")


def handler(event, context):
    """Scan all Zoom accounts for stray recordings"""
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = context.aws_request_id if context is not None else "*NO CONTEXT*"

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    ##STAGE Loop through users
    stage = "Loop through users"
    api_params = {
        "staus": "active",
        "page_size": 300,
    }
    log.debug(stage, reason="Calling Zoom list users API", api_params=api_params)
    api_response = zoom_client.user.list(**api_params)
    log.debug(
        stage,
        reason="Received from Zoom",
        response=api_response,
        response_content=api_response.content,
    )
    api_content = json.loads(api_response.content)
    if not api_response.ok:
        reason = api_content["message"] if "message" in api_content else "unknown"
        log.error(stage, reason=reason, response=api_response.content)
        raise RuntimeError(f"Retrieve Zoom users failed: {reason}")
    log.debug(stage, reason="Received content", api_content=api_content)

    for user in api_content["users"]:
        ##STAGE Check for recordings
        stage = "Check for recordings"

        last_month_date = datetime.now() + relativedelta(months=-1)
        api_params = {
            "user_id": user["id"],
            "page_size": 300,
            "from": last_month_date.strftime("%Y-%m-%d"),
            "to": datetime.now().strftime("%Y-%m-%d"),
        }
        log.debug(
            stage, reason="Calling Zoom list recordings API", api_params=api_params
        )
        api_params["access_token"] = zoom_client.config["token"]
        api_response = zoom_client.recording.list(**api_params)
        log.debug(
            stage,
            reason="Received from Zoom",
            response=api_response,
            response_content=api_response.content,
        )
        api_content = json.loads(api_response.content)
        if not api_response.ok:
            reason = api_content["message"] if "message" in api_content else "unknown"
            log.error(stage, reason=reason, response=api_response.content)
            raise RuntimeError(f"Retrieve Zoom recordings failed: {reason}")
        log.debug(stage, reason="Received content", api_content=api_content)

        ##STAGE Loop through recordings
        stage = "Loop through recordings"
        for meeting in api_content["meetings"]:
            # Was the event long enough to save in the archive?
            meeting_duration = meeting["duration"]
            if int(meeting_duration) < int(MINIMUM_MEETING_DURATION):
                detail = f"Recording ignored; only {meeting_duration} minutes long"
                log.warning(stage, reason="POST rejected", detail=detail)
                continue

            meeting_uuid = base64_to_uuid(meeting["uuid"])
            body = {
                "payload": {
                    "object": meeting,
                },
                "_recording_id": meeting_uuid,
                "download_token": zoom_client.config["token"],
            }
            unique_invocation_name = f"{meeting_uuid}-{time.time()}"

            log.debug(stage, reason="Calling stepfunction", body=body)
            try:
                response = stepfunction_client.start_execution(
                    stateMachineArn=STEP_FUNCTION,
                    name=f"{DEPLOYMENT_STAGE}-{unique_invocation_name}",
                    input=json.dumps(body),
                    traceHeader=meeting_uuid,
                )
            except ClientError as ex:
                log.error(
                    stage,
                    reason=ex.response["Error"]["Code"],
                    response=ex.response,
                    body=body,
                )

            log.info(
                stage,
                reason="Started step function",
                response=response,
                meeting_uuid=meeting_uuid,
            )
