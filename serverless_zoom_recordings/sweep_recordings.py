"""
Ingest metadata into S3 and DynamoDB
"""
import json
import os
from datetime import datetime

import boto3
import structlog
from dateutil.relativedelta import relativedelta
from zoomus import ZoomClient

from .util.identifiers import base64_to_uuid
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
ZOOM_API_KEY = os.environ["ZOOM_API_KEY"]
ZOOM_API_SECRET = os.environ["ZOOM_API_SECRET"]
ZOOM_ACCOUNT_ID = os.environ["ZOOM_ACCOUNT_ID"]
INVOKE_STEPFUNCTION_ARN = os.environ["INVOKE_STEPFUNCTION_ARN"]

lambda_client = boto3.client("lambda")
stepfunction_client = boto3.client("stepfunctions")
zoom_client = ZoomClient(ZOOM_API_KEY, ZOOM_API_SECRET, ZOOM_ACCOUNT_ID)


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
            meeting_uuid = base64_to_uuid(meeting["uuid"])
            body = {
                "payload": {
                    "object": meeting,
                },
                "_recording_id": meeting_uuid,
                "download_token": zoom_client.config["token"],
            }

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
