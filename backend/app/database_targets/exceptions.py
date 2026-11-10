class DatabaseTargetError(Exception):
    """Base error for external database target operations."""


class ConnectionNotFoundError(DatabaseTargetError):
    pass


class TargetConnectionError(DatabaseTargetError):
    pass


class CredentialEncryptionError(DatabaseTargetError):
    pass


class InvalidDatabaseFileError(DatabaseTargetError):
    pass


class UploadTooLargeError(DatabaseTargetError):
    pass


class ConnectionCleanupError(DatabaseTargetError):
    pass
