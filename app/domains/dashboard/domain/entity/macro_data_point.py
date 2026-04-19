from datetime import date


class MacroDataPoint:
    def __init__(self, date: date, value: float):
        self.date = date
        self.value = value
