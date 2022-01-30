"""
Copy recording from Zoom to S3 bucket.

This work is based heavily on [multi-part-upload/handler.py](https://github.com/keithrozario/multi-part-upload/blob/master/serverless/handler.py) from Keith Rozario.
"""
import json
import os

import boto3
import requests
import structlog

from .util.log_config import setup_logging

DEPLOYMENT_STAGE = os.environ["DEPLOYMENT_STAGE"]
RECORDINGS_BUCKET = os.environ["RECORDINGS_BUCKET"]
CHUNK_SIZE = 5 * 1024 * 1024

s3 = boto3.resource("s3")
s3_client = boto3.client("s3")


def handler(sf_input, context):
    """
    Expected keys in the sf_input dictionary to retrieve recording file. (Other
    keys may be present and are copied to the JSON metadata for each retrieved file.)
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

    ##STAGE Set up retrieval
    stage = "Set up retrieval"
    file_extension = f".{sf_input['extension']}" if "extension" in sf_input else ""
    s3_key = f"{sf_input['_recording_id']}/{sf_input['recording_type']}{file_extension}"
    log.debug(
        stage,
        reason="Creating multipart upload",
        s3_key=s3_key,
        bucket=RECORDINGS_BUCKET,
        chunk_size=CHUNK_SIZE,
        url=sf_input["download_url"],
    )
    response = s3_client.create_multipart_upload(Bucket=RECORDINGS_BUCKET, Key=s3_key)
    upload_id = response["UploadId"]
    log = log.bind(upload_id=upload_id)
    log.debug(stage, reason="Created multipart_upload", response=response)

    ##STAGE File transfer
    stage = "File transfer"

    parts = []
    url = f"{sf_input['download_url']}?access_token={sf_input['download_token']}"
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        log.debug(
            stage, reason="Response headers from Zoom", response_headers=r.headers
        )

        # download & upload chunks
        for part_number, chunk in enumerate(r.iter_content(chunk_size=CHUNK_SIZE)):
            response = s3_client.upload_part(
                Bucket=RECORDINGS_BUCKET,
                Key=s3_key,
                UploadId=upload_id,
                PartNumber=part_number + 1,
                Body=chunk,
            )
            log.debug(
                stage, reason=f"Uploaded part {part_number + 1}", response=response
            )
            parts.append(
                {
                    "ETag": response["ETag"],
                    "PartNumber": part_number + 1,
                }
            )

    ##STAGE Complete multi-part upload
    stage = "Complete multi-part upload"
    log.debug(stage, reason="Completing", parts=parts)
    response = s3_client.complete_multipart_upload(
        Bucket=RECORDINGS_BUCKET,
        Key=s3_key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    log.debug(stage, reason="Completed", response=response)
    sf_output = {
        "location": response["Location"],
        "eTag": response["ETag"],
    }
    log.info(stage, reason="File uploaded", details=sf_output)
    sf_output.update(sf_input)

    metadata_key = f"{sf_input['_recording_id']}/{sf_input['recording_type']}.json"
    s3_object = s3.Object(RECORDINGS_BUCKET, metadata_key)
    response = s3_object.put(Body=json.dumps(sf_output), ContentType="application/json")
    log.debug(stage, reason="Put file metadata", response=response)

    return sf_output
