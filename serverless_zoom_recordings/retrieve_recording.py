"""
Copy recording from Zoom to S3 bucket
"""
import os

import boto3
import structlog
from zoomus import ZoomClient

from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_S3_BUCKET = os.environ["RECORDINGS_S3_BUCKET"]
ZOOM_API_KEY = os.environ["ZOOM_API_KEY"]
ZOOM_API_SECRET = os.environ["ZOOM_API_SECRET"]


s3 = boto3.resource("s3")
zoom_client = ZoomClient(ZOOM_API_KEY, ZOOM_API_SECRET)


def handler(sf_input, context):
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = context.aws_request_id if context is not None else "*NO CONTEXT*"

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    if "_recording_id" in sf_input:
        recording_id = sf_input["_recording_id"]
        log = log.bind(recording_id=recording_id)
        log.info("STARTED", reason=recording_id, stepfunction_input=sf_input)
    else:
        log.error(
            "STARTUP FAILED PRECONDITION",
            "_recording_id not found in step function input",
            stepfunction_input=sf_input,
        )
        raise RuntimeError("_recording_id not found in step function input")
    sf_output = {"_recording_id": recording_id}

    ##STAGE Start retrieval
    sf_output["map_output"] = sf_input["recording_type"]

    return sf_output
