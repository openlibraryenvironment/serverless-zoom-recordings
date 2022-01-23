"""
Handle a "Recording Completed" webhook from Zoom.
"""
import json
import os
from base64 import b64decode

import boto3
import structlog

from .util.httpapi_helpers import httpapi_response
from .util.log_config import setup_logging

ZOOM_SECRET_TOKEN = os.environ["ZOOM_SECRET_TOKEN"]
MINIMUM_MEETING_DURATION = os.environ["MINIMUM_MEETING_DURATION"]
sqs = boto3.resource("sqs")
rec_compl_fifo_queue = sqs.Queue(os.environ["RECORDING_COMPLETE_FIFO_QUEUE"])


def handler(event, context):
    setup_logging(context)
    log = structlog.get_logger()
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
    if meeting_duration < MINIMUM_MEETING_DURATION:
        reason = f"Recording ignored; only {meeting_duration} seconds long"
        log.warning("POST rejected", reason=reason)
        return httpapi_response(statusCode=200, body=reason)

    # Push body to queue. 'meeting_uuid' used as a deduplication key
    meeting_uuid = body["payload"]["object"]["uuid"]

    response = rec_compl_fifo_queue.send_message(
        MessageBody=json.dumps(body), MessageGroupId=str(meeting_uuid)
    )
    log.info("Sent event to queue", response=response, meeting_uuid=meeting_uuid)
