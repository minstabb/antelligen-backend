from app.common.exception.app_exception import AppException


class FredApiException(AppException):
    def __init__(self, message: str = "FRED API 데이터 수집에 실패했습니다."):
        super().__init__(status_code=500, message=message)
