import base64
import uuid


def base64_to_uuid(b64_uuid):
    """Convert a base64-encoded UUID back into a canonical UUID string.

    :param b64_uuid: string, Base64-encoded UUID string

    :returns: string, Canonical UUID string
    """

    ## See https://stackoverflow.com/a/23515770/201674
    bin_uuid = base64.b64decode(b64_uuid)
    uuid_str = str(uuid.UUID(bytes=bin_uuid))
    return uuid_str


def parse_organization(meeting_topic):
    """Derive the organizational identifier from the meeting topic string.

    :param meeting_topic: string, Meeting topic from Zoom

    :returns: string, Organization
    """
    if "OLF" in meeting_topic:
        organization = "OLF"
    elif "Foundation" in meeting_topic:
        organization = "OLF"
    elif "FOLIO" in meeting_topic:
        organization = "FOLIO"
    elif "ReShare" in meeting_topic:
        organization = "ReShare"
    elif "VuFind" in meeting_topic:
        organization = "VuFind"
    else:
        organization = "other"

    return organization
