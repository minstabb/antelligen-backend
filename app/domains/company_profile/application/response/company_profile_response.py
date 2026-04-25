from typing import Optional

from pydantic import BaseModel, Field

from app.domains.company_profile.domain.entity.company_profile import CompanyProfile
from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview


class CompanyProfileResponse(BaseModel):
    corp_code: str
    corp_name: str
    corp_name_eng: Optional[str] = None
    stock_name: Optional[str] = None
    stock_code: Optional[str] = None
    ceo_nm: Optional[str] = None
    corp_cls: Optional[str] = None
    corp_cls_label: Optional[str] = None
    jurir_no: Optional[str] = None
    bizr_no: Optional[str] = None
    adres: Optional[str] = None
    hm_url: Optional[str] = None
    ir_url: Optional[str] = None
    phn_no: Optional[str] = None
    fax_no: Optional[str] = None
    induty_code: Optional[str] = None
    est_dt: Optional[str] = None
    acc_mt: Optional[str] = None

    business_summary: Optional[str] = None
    main_revenue_sources: list[str] = Field(default_factory=list)
    overview_source: Optional[str] = None  # "rag_summary" | "llm_only" | None

    @classmethod
    def from_entity(
        cls,
        profile: CompanyProfile,
        overview: Optional[BusinessOverview] = None,
    ) -> "CompanyProfileResponse":
        return cls(
            corp_code=profile.corp_code,
            corp_name=profile.corp_name,
            corp_name_eng=profile.corp_name_eng,
            stock_name=profile.stock_name,
            stock_code=profile.stock_code,
            ceo_nm=profile.ceo_nm,
            corp_cls=profile.corp_cls,
            corp_cls_label=profile.corp_cls_label(),
            jurir_no=profile.jurir_no,
            bizr_no=profile.bizr_no,
            adres=profile.adres,
            hm_url=profile.hm_url,
            ir_url=profile.ir_url,
            phn_no=profile.phn_no,
            fax_no=profile.fax_no,
            induty_code=profile.induty_code,
            est_dt=profile.est_dt,
            acc_mt=profile.acc_mt,
            business_summary=overview.summary if overview else None,
            main_revenue_sources=list(overview.revenue_sources) if overview else [],
            overview_source=overview.source if overview else None,
        )
