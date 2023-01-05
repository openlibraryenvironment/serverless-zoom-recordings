"""
Copy recording from Zoom to S3 bucket.

This work is based heavily on [Python program to stream data from a URL and write it to S3](https://amalgjose.com/2020/08/13/python-program-to-stream-data-from-a-url-and-write-it-to-s3/) from Amal G Jose.
"""
import http.client as http_client
import json
import logging
import os
import urllib

import boto3
import requests
import structlog
from botocore.exceptions import ClientError
from requests.adapters import HTTPAdapter
from requests.models import PreparedRequest
from urllib3 import Retry

from .util.identifiers import parse_organization
from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_BUCKET = os.environ["RECORDINGS_BUCKET"]
CHUNK_SIZE = 5 * 1024 * 1024

s3 = boto3.resource("s3")
s3_client = boto3.client("s3")


def prepped_request_dict(prepped, encoding=None):
    # Based on https://stackoverflow.com/a/60058128/201674
    # prepped has .method, .path_url, .headers and .body attribute to view the request
    encoding = encoding or requests.utils.get_encoding_from_headers(prepped.headers)
    body = prepped.body.decode(encoding) if encoding else "<binary data>"
    request_dict = {
        "method": prepped.method,
        "path_url": prepped.path_url,
        "body": body,
    }
    request_dict["headers"] = prepped.headers
    ## "\n".join(["{}: {}".format(*hv) for hv in prepped.headers.items()])
    return request_dict


def handler(sf_input, context):
    """
    Expected keys in the sf_input dictionary to retrieve recording file. (Other
    keys may be present and are copied to the JSON metadata for each retrieved file.)
        * zoom_parent_meeting_topic
        * recording_type
        * extension
        * download_url
        * download_token
        * _recording_id
        * mime_type
    """
    setup_logging()
    log = structlog.get_logger()
    aws_request_id = context.aws_request_id if context is not None else "*NO CONTEXT*"

    log = structlog.get_logger()
    log = log.bind(aws_request_id=aws_request_id)

    if "_recording_id" in sf_input and "recording_type" in sf_input:
        recording_id = sf_input["_recording_id"]
        log = log.bind(recording_id=recording_id)
        log = log.bind(recording_type=sf_input["recording_type"])
        log.info("STARTED", reason=recording_id, stepfunction_input=sf_input)
    else:
        log.error(
            "STARTUP FAILED PRECONDITION",
            "_recording_id not found in step function input",
            stepfunction_input=sf_input,
        )
        raise RuntimeError("_recording_id not found in step function input")
    sf_output = {"_recording_id": recording_id}

    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.propagate = True

    ##STAGE File transfer
    stage = "File transfer"
    file_extension = f".{sf_input['extension']}" if "extension" in sf_input else ""
    s3_key = f"{sf_input['_recording_id']}/{sf_input['recording_type']}{file_extension}"
    req = PreparedRequest()
    req.prepare_url(
        sf_input["download_url"], {"access_token": sf_input["download_token"]}
    )
    log.debug(
        stage,
        reason="Ready to start retrieval",
        details={
            "file_extension": file_extension,
            "s3_key": s3_key,
            "zoom_url": req.url,
        },
    )

    # url = f"{sf_input['download_url']}?access_token={sf_input['download_token']}"
    zoom_session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=4,
            backoff_factor=1,
            allowed_methods=None,
            status_forcelist=[429, 500, 502, 503, 504],
        )
    )
    zoom_session.mount("http://", adapter)
    zoom_session.mount("https://", adapter)
    s3_object = s3.Object(RECORDINGS_BUCKET, s3_key)

    # We're turning on some extra logging here because upload_fileobj() is an async function
    requests_log.setLevel(logging.DEBUG)
    http_client.HTTPConnection.debuglevel = 1
    with zoom_session.get(req.url, stream=True, timeout=10) as zoom_response:
        zoom_response.raise_for_status()
        log.debug(
            stage,
            reason="Response headers from Zoom",
            response_headers=zoom_response.headers,
        )

        with zoom_response as part:
            part.raw.decode_content = True
            s3_transfer_conf = boto3.s3.transfer.TransferConfig(
                multipart_threshold=10000, max_concurrency=4
            )
            s3_client.upload_fileobj(
                part.raw,
                Bucket=RECORDINGS_BUCKET,
                Key=s3_key,
                Config=s3_transfer_conf,
                ExtraArgs={"ContentType": sf_input["mime_type"]},
            )

        try:
            s3_object.wait_until_exists()
        except ClientError as error:
            log.error(stage, reason="AWS s3.upload_fileobj() error", details=error)
            raise error

        # Turning off extra logging
        requests_log.setLevel(logging.WARN)
        http_client.HTTPConnection.debuglevel = 0

        sf_output["eTag"] = s3_object.e_tag.strip('"')
        sf_output[
            "location"
        ] = f"""https://{RECORDINGS_BUCKET}.s3.amazonaws.com/{urllib.parse.quote(s3_key, safe="~()*!.'")}"""

    log.info(stage, reason="File uploaded", details=sf_output)
    sf_output.update(sf_input)

    metadata_key = f"{sf_input['_recording_id']}/{sf_input['recording_type']}.json"
    s3_object = s3.Object(RECORDINGS_BUCKET, metadata_key)
    response = s3_object.put(
        Body=json.dumps(sf_output),
        ContentType="application/json",
        Tagging=f"Purpose=recording-site-{parse_organization(sf_input['zoom_parent_meeting_topic'])}",
    )
    log.debug(stage, reason="Put file metadata", response=response)

    return sf_output
