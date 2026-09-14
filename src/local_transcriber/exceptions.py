"""Domain exceptions shared by queue and persistence layers."""


class LeaseOwnershipLost(Exception):
    """The worker no longer owns a valid lease for the claimed job."""


class RecordingHasActiveJobsError(RuntimeError):
    """A recording cannot be removed while local work still references it."""
