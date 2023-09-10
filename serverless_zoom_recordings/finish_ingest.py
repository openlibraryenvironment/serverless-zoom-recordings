"""
Perform the final actions of the ingestion step function.

"""
import json
import os

import boto3
import structlog
from zoomus import ZoomClient

from .util.identifiers import parse_organization
from .util.log_config import setup_logging
from .util.recording_path import recording_path

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_BUCKET = os.environ["RECORDINGS_BUCKET"]
ZOOM_API_KEY = os.environ["ZOOM_API_KEY"]
ZOOM_API_SECRET = os.environ["ZOOM_API_SECRET"]
ZOOM_ACCOUNT_ID = os.environ["ZOOM_ACCOUNT_ID"]
MEETINGS_DYNAMODB_TABLE = os.environ["MEETINGS_DYNAMODB_TABLE"]
NOTIFY_WEB_BUILDER_QUEUE = os.environ["NOTIFY_WEB_BUILDER_QUEUE"]

s3 = boto3.resource("s3")
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
meetings_table = dynamodb.Table(MEETINGS_DYNAMODB_TABLE)
sqs = boto3.resource("sqs")
web_builder_notify = sqs.Queue(NOTIFY_WEB_BUILDER_QUEUE)

zoom_client = ZoomClient(ZOOM_API_KEY, ZOOM_API_SECRET, ZOOM_ACCOUNT_ID)


def handler(sf_input, context):
    """Handle Step Function"""
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
            reason="_recording_id not found in step function input",
            stepfunction_input=sf_input,
        )
        raise RuntimeError("_recording_id not found in step function input")
    sf_output = {"_recording_id": recording_id}

    ##STAGE Save recording document
    stage = "Save recording document"
    organization = parse_organization(sf_input["parent_meeting_metadata"]["topic"])

    path = recording_path(
        organization=organization,
        meeting_topic=sf_input["parent_meeting_metadata"]["topic"],
        meeting_start=sf_input["past_meeting_metadata"]["start_time"],
    )

    recording_document = {
        "recording_id": recording_id,
        "recording_path": path,
        "meeting_uuid": sf_input["recording_metadata"]["payload"]["object"]["uuid"],
        "parent_meeting_uuid": sf_input["parent_meeting_metadata"]["uuid"],
        "organization": organization,
        "meeting_id": sf_input["parent_meeting_metadata"]["id"],
        "meeting_topic": sf_input["parent_meeting_metadata"]["topic"],
        "start_time": sf_input["past_meeting_metadata"]["start_time"],
        "end_time": sf_input["past_meeting_metadata"]["end_time"],
        "password": sf_input["parent_meeting_metadata"].get("password", ""),
        "host_id": sf_input["parent_meeting_metadata"]["host_id"],
    }
    recording_document["files"] = []
    for file in sf_input["recordings_map_results"]:
        file_data = {
            "recording_type": file["recording_type"],
            "s3_url": file["location"],
            "etag": file["eTag"],
            "zoom_file_size": file["zoom_file_size"],
            "mime_type": file["mime_type"],
        }
        recording_document["files"].append(file_data)
    log.info(stage, reason="Recording document", recording_document=recording_document)
    recording_json_key = f"{recording_id}/recording_document.json"
    s3_object = s3.Object(RECORDINGS_BUCKET, recording_json_key)
    response = s3_object.put(
        Body=json.dumps(recording_document), ContentType="application/json"
    )
    log.debug(stage, reason="Put recording document to S3", response=response)

    response = meetings_table.put_item(Item=recording_document)
    log.debug(stage, reason="Put recording document to DB", response=response)

    ##STAGE Delete recording from Zoom
    stage = "Delete recording from Zoom"
    if DEPLOYMENT_STAGE == "prod":
        api_response = zoom_client.recording.delete(
            meeting_id=sf_input["recording_metadata"]["payload"]["object"]["uuid"]
        )
        api_content = json.loads(api_response.content) if api_response.content else {}
        if not api_response.ok:
            reason = api_content["message"] if "message" in api_content else "unknown"
            log.warning(
                stage,
                reason=reason,
                response=api_response,
                response_content=api_response.content,
            )
        else:
            log.debug(
                stage,
                reason="Deleted recording",
                response=api_response,
                response_content=api_response.content,
            )
    else:
        log.info(stage, reason="Not in production deployment, recording not deleted")

    ##STAGE Send message to website builder routine
    stage = "Notify web-builder"
    response = web_builder_notify.send_message(
        MessageBody=json.dumps(recording_document)
    )
    log.info(stage, reason="Complete", response=response, body=recording_document)

    return sf_output
