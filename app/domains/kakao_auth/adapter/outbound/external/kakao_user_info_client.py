import httpx

from app.domains.kakao_auth.application.port.out.kakao_user_info_port import KakaoUserInfoPort
from app.domains.kakao_auth.domain.entity.kakao_user_info import KakaoUserInfo

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"


class KakaoUserInfoClient(KakaoUserInfoPort):

    async def fetch_user_info(self, access_token: str) -> KakaoUserInfo:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                KAKAO_USER_INFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            body = response.json()
            error_desc = body.get("msg", "Kakao 사용자 정보 조회 실패")
            raise ValueError(error_desc)

        body = response.json()
        kakao_account = body.get("kakao_account", {})
        profile = kakao_account.get("profile", {})

        return KakaoUserInfo(
            kakao_id=body["id"],
            nickname=profile.get("nickname"),
            email=kakao_account.get("email"),
        )
