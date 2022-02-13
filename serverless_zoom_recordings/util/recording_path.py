import re
from datetime import datetime, timedelta

import pytz


def project_time(timestamp, do_round=False, pretty=False):
    """Convert Zoom time string into the project's timezone (US/Eastern).

    :param timestamp: string, Timestamp from Zoom
    :param round: boolean, Perform rounding to the nearest 5 minute mark
    :param pretty: boolean, Returning human-readable string versus ISO time string

    :returns: string, Formatted time
    """
    # Convert to Eastern U.S. time
    eastern_us_tz = pytz.timezone("US/Eastern")
    ## See https://stackoverflow.com/a/62769371/201674
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    dt = dt.replace(tzinfo=pytz.UTC).astimezone(eastern_us_tz)

    # Round to nearest 5 minute mark
    ## See https://stackoverflow.com/a/10854034/201674
    if do_round:
        round_to = 5 * 60
        seconds = (dt.replace(tzinfo=None) - dt.min).seconds
        rounding = (seconds + round_to / 2) // round_to * round_to
        dt = dt + timedelta(0, rounding - seconds, -dt.microsecond)

    if pretty:
        output = dt.strftime("%e-%b-%Y %H:%M Eastern U.S. time")
    else:
        output = dt.strftime("%Y-%m-%dT%H:%M")

    return output


def recording_path(organization=None, meeting_topic=None, meeting_start=None):
    """Construct path or partial path to the recording.

    :param organization: string, Organization name
    :param meeting_topic: string, Meeting topic
    :param meeting_start: string, Timestamp of meeting start from Zoom

    :returns: string, File path corresponding to input parameters
    """
    if meeting_topic:
        # Normalize the meeting topic to a URL-friendly form
        topic = re.sub(
            r"\s*\(?" + organization + r"\)?\s*", "", meeting_topic, flags=re.IGNORECASE
        )
        topic = topic.translate({ord(c): " " for c in r"!@#$%^&*()[]{};:,./<>?\|`~=_+"})
        topic = re.sub(r"[-\W]+", "-", topic).strip().lower().strip("-")
    else:
        topic = None

    if meeting_start:
        meeting_start_path = project_time(meeting_start, do_round=True, pretty=False)
    else:
        meeting_start_path = None

    path = organization.lower()
    if topic:
        path = f"{path}/{topic}"
        if meeting_start_path:
            path = f"{path}/{meeting_start_path}"

    return path
