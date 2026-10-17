from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: SecretStr


class Account(Login):
    role: str = "member"


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    provider_id: str
    label: str
    key: SecretStr


class Rotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: SecretStr


class Setup(Login):
    setup_token: SecretStr
    team_name: str = "团队实验室"


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr
    password: SecretStr


class MasterRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr
    expected_generation: int = Field(strict=True, ge=1)
