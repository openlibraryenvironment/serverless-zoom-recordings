import re
from datetime import datetime, timedelta

import pytz


def project_dt(timestamp):
    eastern_us_tz = pytz.timezone("US/Eastern")
    ## See https://stackoverflow.com/a/62769371/201674
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    dt = dt.replace(tzinfo=pytz.UTC).astimezone(eastern_us_tz)
    return dt


def recording_path(organization=None, meeting_topic=None, meeting_start=None):
    # Normalize the meeting topic to a URL-friendly form
    topic = re.sub(
        r"\s*\(?" + organization + r"\)?\s*", "", meeting_topic, flags=re.IGNORECASE
    )
    topic = topic.translate({ord(c): " " for c in r"!@#$%^&*()[]{};:,./<>?\|`~=_+"})
    topic = re.sub(r"[-\W]+", "-", topic).strip().lower()

    # Round meeting start to the nearest 5 minutes and put into U.S. Eastern TZ
    ## See https://stackoverflow.com/a/10854034/201674
    round_to = 5 * 60
    dt = project_dt(meeting_start)
    seconds = (dt.replace(tzinfo=None) - dt.min).seconds
    rounding = (seconds + round_to / 2) // round_to * round_to
    rounded = dt + timedelta(0, rounding - seconds, -dt.microsecond)

    path = f"{organization.lower()}/{topic}/{rounded.strftime('%Y-%m-%dT%H:%M')}"

    return path
