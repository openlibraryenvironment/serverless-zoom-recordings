"""
Configure logging for the Lambda

Based on concepts in:
https://github.com/stevezieglerva/aws-sqs-to-es-bulk/blob/fb716fd393cced8ed04aca0a1f4b9bacbfef1c4c/lambda_function.py
https://github.com/jkpl/eks-auth-sync/blob/84ef8f0030881497cfbc5c0698a579508d5edfc0/src/eks_auth_sync/__main__.py
"""
import json
import logging
import sys
from typing import List

import structlog
from structlog.processors import _json_fallback_handler
from structlog.types import Any, Callable, EventDict, Union

_NOISY_LOG_SOURCES = (
    "boto",
    "boto3",
    "botocore",
    "urllib3",
    "s3transfer",
)


class AWSCloudWatchLogs:
    """
    Render a log line compatible with AWS CloudWatch Logs.  This is a copy
    and modification of `structlog.processors.JSONRenderer`

    Render the ``event_dict`` using ``serializer(event_dict, **json_kw)``.
    :param callouts: Are printed in clear-text on the front of the log line.
        Only the first two items of this list are called out.
    :param json_kw: Are passed unmodified to *serializer*.  If *default*
        is passed, it will disable support for ``__structlog__``-based
        serialization.
    :param serializer: A :func:`json.dumps`-compatible callable that
        will be used to format the string.  This can be used to use alternative
        JSON encoders like `simplejson
        <https://pypi.org/project/simplejson/>`_ or `RapidJSON
        <https://pypi.org/project/python-rapidjson/>`_ (faster but Python
        3-only) (default: :func:`json.dumps`).
    """

    def __init__(
        self,
        callouts: List = None,
        serializer: Callable[..., Union[str, bytes]] = json.dumps,
        **dumps_kw: Any,
    ) -> None:
        try:
            self._callout_one_key = callouts[0]
        except IndexError:
            self._callout_one_key = None
        try:
            self._callout_two_key = callouts[1]
        except IndexError:
            self._callout_two_key = None
        dumps_kw.setdefault("default", _json_fallback_handler)
        self._dumps_kw = dumps_kw
        self._dumps = serializer

    def __call__(self, _, name: str, event_dict: EventDict) -> Union[str, bytes]:
        """
        The return type of this depends on the return type of self._dumps.
        """
        if self._callout_one_key:
            callout_one = event_dict.get(self._callout_one_key, "")
        else:
            callout_one = "none"
        if self._callout_two_key:
            callout_two = event_dict.get(self._callout_two_key, "")
        else:
            callout_two = "none"
        return f'[{name.upper()}] "{callout_one}" "{callout_two}" ' + self._dumps(
            event_dict, **self._dumps_kw
        )


_PROCESSORS = (
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
    structlog.threadlocal.merge_threadlocal,
    AWSCloudWatchLogs(callouts=["event", "reason"]),
)


def setup_logging():
    """
    Configure logging for the application.
    """

    # Structlog configuration
    structlog.configure(
        processors=list(_PROCESSORS),
        context_class=dict,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Stdlib logging configuration. `force` was added to reset the AWS-Lambda-supplied log handlers.
    # see: https://stackoverflow.com/questions/37703609/using-python-logging-with-aws-lambda#comment120413034_45624044
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG,
        force=True,
    )
    for source in _NOISY_LOG_SOURCES:
        logging.getLogger(source).setLevel(logging.WARNING)
