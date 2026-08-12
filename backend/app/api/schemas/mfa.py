from pydantic import BaseModel


class EnrollResponse(BaseModel):
    otpauth_uri: str
    qr_code_png_base64: str


class EnrollConfirmRequest(BaseModel):
    code: str


class EnrollConfirmResponse(BaseModel):
    recovery_codes: list[str]


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


class SetupEnrollRequest(BaseModel):
    mfa_token: str


class SetupConfirmRequest(BaseModel):
    mfa_token: str
    code: str


class SetupConfirmResponse(BaseModel):
    status: str
    recovery_codes: list[str]
