import strawberry


@strawberry.type
class CallbackResponse:
    message: str
    success: bool = True
