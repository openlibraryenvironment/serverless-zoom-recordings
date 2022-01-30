"""
Ingest metadata into S3 and DynamoDB
"""
import json
import os

import boto3
import structlog
from zoomus import ZoomClient

from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_BUCKET = os.environ["RECORDINGS_BUCKET"]
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

    ##STAGE Store recording details in S3 and database
    stage = "Store recording details"
    recording_json_key = f"{recording_id}/recording.json"
    s3_object = s3.Object(RECORDINGS_BUCKET, recording_json_key)
    response = s3_object.put(Body=json.dumps(sf_input), ContentType="application/json")
    log.debug(stage, reason="Put recording event details", response=response)
    sf_output["recording_metadata"] = sf_input

    ##STAGE Get past meeting metadata from Zoom, store in S3 folder and database
    sf_output["past_meeting_metadata"] = retrieve_zoom_metadata(
        stage="Retrieve past meeting details",
        meeting_id=sf_input["payload"]["object"]["uuid"],
        zoom_api=zoom_client.past_meeting.get,
        file_key=f"{recording_id}/past_meeting.json",
        log=log,
    )

    ##STAGE Get parent meeting metadata from Zoom, store in S3 folder and database
    sf_output["parent_meeting_metadata"] = retrieve_zoom_metadata(
        stage="Retrieve parent meeting details",
        id=sf_output["past_meeting_metadata"]["id"],
        zoom_api=zoom_client.meeting.get,
        file_key=f"{recording_id}/meeting.json",
        log=log,
    )

    ##STAGE Prepare parallel recording retrieval
    stage = "Prepare recordings array"
    download_token = sf_input["download_token"]
    sf_output["recordings_map_input"] = []
    for recording in sf_input["payload"]["object"]["recording_files"]:
        recording_metadata = {
            "recording_type": recording["recording_type"],
            "download_url": recording["download_url"],
            "zoom_file_id": recording["id"],
            "zoom_meeting_id": recording["meeting_id"],
            "zoom_parent_meeting_id": sf_output["parent_meeting_metadata"]["id"],
            "zoom_parent_meeting_topic": sf_output["parent_meeting_metadata"]["topic"],
            "zoom_parent_meeting_password": sf_output["parent_meeting_metadata"][
                "password"
            ],
            "zoom_file_size": recording["file_size"],
            "recording_start": recording["recording_start"],
            "recording_end": recording["recording_end"],
            "download_token": download_token,
            "_recording_id": recording_id,
        }
        if recording["file_type"] == "M4A":
            recording_metadata["mime_type"] = "audio/m4a"
            recording_metadata["extension"] = "m4a"
        elif recording["file_type"] == "MP4":
            recording_metadata["mime_type"] = "video/mp4"
            recording_metadata["extension"] = "mp4"
        elif recording["file_type"] == "TIMELINE":
            recording_metadata["mime_type"] = "application/json"
            recording_metadata["extension"] = "json"
        elif recording["file_type"] == "TRANSCRIPT":
            recording_metadata["mime_type"] = "text/vtt"
            recording_metadata["extension"] = "vtt"
        elif recording["file_type"] == "CHAT":
            recording_metadata["mime_type"] = "text/plain"
            recording_metadata["extension"] = "txt"
        elif recording["file_type"] == "CC":
            recording_metadata["mime_type"] = "text/vtt"
            recording_metadata["extension"] = "vtt"
        elif recording["file_type"] == "CSV":
            recording_metadata["mime_type"] = "text/csv"
            recording_metadata["extension"] = "csv"
        else:
            recording_metadata["mime_type"] = "application/octet-stream"
        sf_output["recordings_map_input"].append(recording_metadata)
        sf_output["recordings_map_results"] = []
    log.info(stage, reason="Recordings", recordings=sf_output["recordings_map_input"])

    return sf_output


def retrieve_zoom_metadata(
    stage=None, zoom_api=None, file_key=None, log=None, **attributes
):
    if "id" in attributes:
        api_response = zoom_api(id=attributes["id"])
    elif "meeting_id" in attributes:
        api_response = zoom_api(meeting_id=attributes["meeting_id"])
    log.debug(
        stage,
        reason="Received Zoom",
        response=api_response,
        response_content=api_response.content,
    )
    api_content = json.loads(api_response.content)
    if not api_response.ok:
        reason = api_content["message"] if "message" in api_content else "unknown"
        log.error(stage, reason=reason, response=api_response.content)
        raise RuntimeError(f"Retrieve Zoom meeting details failed: {reason}")

    if file_key:
        s3_object = s3.Object(RECORDINGS_BUCKET, file_key)
        response = s3_object.put(
            Body=json.dumps(api_content), ContentType="application/json"
        )
        log.debug(stage, reason="Put meeting details", response=response)
        log.info(stage, reason="Meeting details", details=api_content)

    return api_content
