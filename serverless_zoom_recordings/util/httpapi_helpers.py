def httpapi_response(
    statusCode="500",
    isBase64Encoded=False,
    body="System error",
    contentType="text/plain",
):
    return dict(
        {
            "statusCode": statusCode,
            "isBase64Encoded": isBase64Encoded,
            "body": body,
            "headers": {"content-type": contentType},
        }
    )
