class SQLGenerationError(Exception):
    """Base error for SQL generation failures."""


class MissingGroqAPIKeyError(SQLGenerationError):
    pass


class GroqProviderError(SQLGenerationError):
    pass


class SchemaContextTooLargeError(SQLGenerationError):
    pass
