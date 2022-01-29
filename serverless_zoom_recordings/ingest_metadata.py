"""
Ingest metadata into S3 and DynamoDB
"""
import json
import os
from base64 import b64decode

import boto3
import structlog

from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]


def handler(event, context):
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = "*NO CONTEXT*"
    if context is not None:
        aws_request_id = context.aws_request_id

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    log.info("STARTED", stepfunction_input=event)
