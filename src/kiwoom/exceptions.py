class KiwoomError(Exception):
    pass


class KiwoomLoginError(KiwoomError):
    pass


class KiwoomTRError(KiwoomError):
    pass


class KiwoomOrderError(KiwoomError):
    pass


class KiwoomRealTimeError(KiwoomError):
    pass


LOGIN_ERROR_CODES = {
    0:    "정상",
    -100: "사용자 정보교환 실패",
    -101: "서버 접속 실패",
    -102: "버전처리 실패",
}

TR_ERROR_CODES = {
    0:   "정상",
    -1:  "조회 오류",
    -2:  "서버 응답 오류",
    -3:  "사용자 ID 오류",
    -4:  "연결 끊김",
    -5:  "조회 한도 초과",
    -100: "사용자 정보교환 실패",
    -200: "시세 조회 오류",
    -201: "체결 잔고 조회 오류",
}
