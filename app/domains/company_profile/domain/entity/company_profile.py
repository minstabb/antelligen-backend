from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CompanyProfile:
    corp_code: str
    corp_name: str
    corp_name_eng: Optional[str]
    stock_name: Optional[str]
    stock_code: Optional[str]
    ceo_nm: Optional[str]
    corp_cls: Optional[str]
    jurir_no: Optional[str]
    bizr_no: Optional[str]
    adres: Optional[str]
    hm_url: Optional[str]
    ir_url: Optional[str]
    phn_no: Optional[str]
    fax_no: Optional[str]
    induty_code: Optional[str]
    est_dt: Optional[str]
    acc_mt: Optional[str]

    CORP_CLS_LABELS = {
        "Y": "유가증권(KOSPI)",
        "K": "코스닥(KOSDAQ)",
        "N": "코넥스(KONEX)",
        "E": "기타",
        "US": "미국 (NASDAQ/NYSE)",
    }

    def corp_cls_label(self) -> Optional[str]:
        if not self.corp_cls:
            return None
        return self.CORP_CLS_LABELS.get(self.corp_cls, self.corp_cls)
