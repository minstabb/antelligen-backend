from enum import Enum


class Sector(str, Enum):
    ENTERTAINMENT = "ENTERTAINMENT"
    TECH = "TECH"
    FINANCE = "FINANCE"
    BIO = "BIO"
    ENERGY = "ENERGY"
    UNKNOWN = "UNKNOWN"
