from app.common.exception.app_exception import AppException


class NasdaqDataFetchException(AppException):
    def __init__(self, message: str = "나스닥 데이터 수집에 실패했습니다."):
        super().__init__(status_code=500, message=message)
