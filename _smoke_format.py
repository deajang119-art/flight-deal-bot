"""텔레그램 메시지 서식 확인. 토큰 없이 화면에만 찍는다.

버튼(inline keyboard)도 같이 찍는다. 주소가 http 로 시작하지 않으면 텔레그램이
메시지를 통째로 거부하니, 여기서 눈으로 확인하고 넘어가는 게 안전하다.
"""
import notify, weather, storage
from deals import Deal
from destinations import BY_IATA
from flights import Offer
from packages import Package, PackageDeal

storage.init()


def show_buttons(buttons):
    """말풍선 아래 버튼이 어떻게 깔리는지 그대로 그려 본다."""
    markup = notify.keyboard(buttons)
    if not markup:
        print("  [버튼 없음]")
        return
    for row in markup["inline_keyboard"]:
        print("  " + "   ".join(f"[ {b['text']} ]" for b in row))
    for row in markup["inline_keyboard"]:
        for b in row:
            assert b["url"].startswith("http"), f"주소가 이상하다: {b['url']}"
            print(f"    {b['text']} → {b['url']}")


dest = BY_IATA["BKK"]
w = weather.score(dest, "2026-11-12")
offer = Offer(
    origin="ICN", destination="BKK", depart_date="2026-11-12",
    return_date="2026-11-15", days=3, price=312400, airline="TG",
    transfers=0, link="https://www.aviasales.com/search/ICN1211BKK1",
)
deal = Deal(
    offer=offer, dest=dest, baseline=548000, drop_pct=43.0,
    weather_score=w["score"] or 80.0, weather_summary=w["summary"],
    samples=41, is_record_low=True, notes=["관측 이래 최저가", "직항"],
)

print("=" * 60)
print("항공권 딜")
print("=" * 60)
print(notify.format_deal(deal))
show_buttons(notify.deal_buttons(deal))

# Drops 방식(7일 최저가 대비)으로 걸린 경우
dest2 = BY_IATA["FUK"]
w2 = weather.score(dest2, "2026-10-09")
offer2 = Offer(
    origin="ICN", destination="FUK", depart_date="2026-10-09",
    return_date="2026-10-12", days=3, price=148000, airline="7C",
    transfers=0, link="",
)
deal2 = Deal(
    offer=offer2, dest=dest2, baseline=196000, drop_pct=24.5,
    weather_score=w2["score"] or 80.0, weather_summary=w2["summary"],
    samples=63, basis="7일 최저가", week_low_pct=22.1,
    notes=["7일 최저가(190,000원)보다 22% 더 쌈", "직항"],
)
print()
print("=" * 60)
print("항공권 딜 — 스카이스캐너 Drops 방식으로 걸린 경우")
print("=" * 60)
print(notify.format_deal(deal2))
show_buttons(notify.deal_buttons(deal2))

pkg = Package(
    source="webtour", source_ko="웹투어", code="APAVN0110",
    title="[다낭 자유여행] 벨 메종 파로샌드 #전일정 조식 4/5일",
    price=398000, url="https://m.webtour.com/ap/ap_detail.asp?GdsCode=APAVN0110",
    list_price=569000, dest_key="DAD", is_fit=True, days=5,
)
pdeal = PackageDeal(pkg=pkg, baseline=612000, drop_pct=35.0,
                    basis="다낭(베트남) 5일 평균", samples=14,
                    notes=["정가 569,000원", "5일"])

print()
print("=" * 60)
print("여행사 자유여행 특가")
print("=" * 60)
print(notify.format_package(pdeal))
show_buttons(notify.package_buttons(pdeal))
