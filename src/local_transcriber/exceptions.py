"""Domain exceptions shared by queue and persistence layers."""


class LeaseOwnershipLost(Exception):
    """The worker no longer owns a valid lease for the claimed job."""
