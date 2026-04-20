from app.common.exception.app_exception import AppException


class StockDataFetchException(AppException):
    def __init__(self, message: str = "종목 데이터 수집에 실패했습니다."):
        super().__init__(status_code=500, message=message)


class InvalidTickerException(AppException):
    def __init__(self, ticker: str):
        super().__init__(status_code=404, message=f"존재하지 않는 ticker입니다: {ticker}")
