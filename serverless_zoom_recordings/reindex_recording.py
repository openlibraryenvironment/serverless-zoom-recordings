"""
Perform the final actions of the ingestion step function.

"""
import json
import os

import boto3
import structlog

from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_BUCKET = os.environ["RECORDINGS_BUCKET"]
MEETINGS_DYNAMODB_TABLE = os.environ["MEETINGS_DYNAMODB_TABLE"]
NOTIFY_WEB_BUILDER_QUEUE = os.environ["NOTIFY_WEB_BUILDER_QUEUE"]

s3 = boto3.resource("s3")
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
meetings_table = dynamodb.Table(MEETINGS_DYNAMODB_TABLE)
sqs = boto3.resource("sqs")
web_builder_notify = sqs.Queue(NOTIFY_WEB_BUILDER_QUEUE)


def handler(recording_document, context):
    """Handle Step Function"""
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = context.aws_request_id if context is not None else "*NO CONTEXT*"
    log = log.bind(aws_request_id=aws_request_id)

    if "recording_id" in recording_document:
        recording_id = recording_document["recording_id"]
        log = log.bind(recording_id=recording_id)
        log.info("STARTED", reason=recording_id, function_input=recording_document)
    else:
        log.error(
            "STARTUP FAILED PRECONDITION",
            reason="recording_id not found in function input",
            function_input=recording_document,
        )
        raise RuntimeError("_recording_id not found in step function input")
    fn_output = {"recording_id": recording_id}

    ##STAGE Validate recording document
    stage = "Validate recording document"
    required_fields = [
        "recording_path",
        "meeting_uuid",
        "parent_meeting_uuid",
        "organization",
        "meeting_id",
        "meeting_topic",
        "start_time",
        "end_time",
        "password",
        "host_id",
    ]
    for field in required_fields:
        if field not in recording_document:
            log.error(
                stage,
                reason="FieldNotFound",
                missing_field=field,
                recording_document=recording_document,
            )
            fn_output["error"] = "FieldNotFound"
            fn_output["missing_field"] = field
            return fn_output

    ##STAGE Store document
    stage = "Store Document"
    recording_json_key = f"{recording_id}/recording_document.json"
    s3_object = s3.Object(RECORDINGS_BUCKET, recording_json_key)
    response = s3_object.put(
        Body=json.dumps(recording_document), ContentType="application/json"
    )
    log.info(stage, reason="Put recording document to S3", response=response)
    fn_output["s3_object_put_response"] = response

    response = meetings_table.put_item(Item=recording_document)
    log.info(stage, reason="Put recording document to DB", response=response)
    fn_output["dyamodb_put_item_response"] = response

    ##STAGE Send message to website builder routine
    stage = "Notify web-builder"
    response = web_builder_notify.send_message(
        MessageBody=json.dumps(recording_document)
    )
    log.info(stage, reason="Complete", response=response, body=recording_document)
    fn_output["sqs_send_message_response"] = response
    fn_output["result"] = "success"

    return fn_output
