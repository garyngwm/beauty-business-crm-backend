from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


# Automatically converts server's response to camelCase
class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, validate_by_alias=True
    )
