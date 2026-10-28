import time

import pytest

from arturokai.store import DAY, NotEnoughCredits, Store, StoreError

PLANS = {
    "free": {"name": "Бесплатный", "credits": 10, "reset_days": 1},
    "start": {"name": "Старт", "credits": 100, "days": 30},
}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "db.sqlite", PLANS)


def test_register_login(store):
    u = store.create_user("artur", "secret1")
    assert u["plan"] == "free" and u["credits"] == 10
    assert store.authenticate("ARTUR", "secret1")["id"] == u["id"]
    assert store.authenticate("artur", "wrong") is None
    with pytest.raises(StoreError):
        store.create_user("artur", "another1")
    with pytest.raises(StoreError):
        store.create_user("x", "secret1")


def test_charge_percent_and_bonus(store):
    u = store.create_user("user1", "secret1")
    store.charge(u["id"], 4, "Фото")
    s = store.summary(store.user(u["id"]))
    assert (s["credits"], s["percent"]) == (6, 60)
    code = store.create_codes("credits", 1, credits=50)[0]
    assert "50" in store.redeem(u["id"], code)
    store.charge(u["id"], 10, "Видео")  # 6 тарифных + 4 бонусных
    u2 = store.user(u["id"])
    assert (u2["credits"], u2["bonus"]) == (0, 46)
    with pytest.raises(NotEnoughCredits):
        store.charge(u["id"], 1000, "Видео")


def test_plan_code_extend_and_expire(store):
    u = store.create_user("user2", "secret1")
    a, b = store.create_codes("plan", 2, plan="start")
    store.redeem(u["id"], a)
    s = store.summary(store.user(u["id"]))
    assert (s["plan"], s["credits"], s["days_left"]) == ("start", 100, 30)
    with pytest.raises(StoreError, match="уже активирован"):
        store.redeem(u["id"], a)
    store.redeem(u["id"], b.lower())  # тот же тариф — продлевается, кредиты складываются
    s = store.summary(store.user(u["id"]))
    assert (s["credits"], s["quota"], s["days_left"]) == (200, 200, 60)
    # подписка закончилась — снова бесплатный тариф
    store.db.execute("UPDATE users SET plan_until = ? WHERE id = ?", (time.time() - 1, u["id"]))
    assert store.user(u["id"])["plan"] == "free"


def test_free_daily_reset(store):
    u = store.create_user("user3", "secret1")
    store.charge(u["id"], 10, "Фото")
    store.db.execute("UPDATE users SET period_start = ? WHERE id = ?", (time.time() - DAY - 1, u["id"]))
    assert store.user(u["id"])["credits"] == 10


def test_bad_codes(store):
    u = store.create_user("user4", "secret1")
    with pytest.raises(StoreError, match="не найден"):
        store.redeem(u["id"], "ARTK-AAAA-BBBB-CCCC")
    with pytest.raises(StoreError):
        store.create_codes("plan", 1, plan="free")
    codes = store.create_codes("plan", 20, plan="start")
    assert len(set(codes)) == 20 and all(c.startswith("ARTK-") and len(c) == 19 for c in codes)


def test_pricing_override_in_place_and_persist(tmp_path):
    plans = {"free": {"name": "Бесплатный", "credits": 10, "reset_days": 1, "price": "0 ₽"},
             "start": {"name": "Старт", "credits": 100, "days": 30, "price": "490 ₽"}}
    costs = {"image": 2, "video_second": 3, "chat": 1}
    db = tmp_path / "p.db"
    store = Store(db, plans, costs)
    store.set_pricing({"costs": {"image": 5}, "plans": {"start": {"price": "990 ₽", "credits": 200}}})
    # те же словари меняются «на месте» — их видят все, кто держит ссылку
    assert costs["image"] == 5 and plans["start"]["price"] == "990 ₽" and plans["start"]["credits"] == 200
    # и сохраняется между перезапусками
    plans2 = {"free": {"name": "Бесплатный", "credits": 10, "reset_days": 1, "price": "0 ₽"},
              "start": {"name": "Старт", "credits": 100, "days": 30, "price": "490 ₽"}}
    costs2 = {"image": 2, "video_second": 3, "chat": 1}
    Store(db, plans2, costs2)
    assert costs2["image"] == 5 and plans2["start"]["credits"] == 200


def test_sheets_crud(store):
    u = store.create_user("tabler", "secret1")
    s = store.create_sheet(u["id"], "Бюджет", rows=3, cols=2)
    assert s["name"] == "Бюджет" and s["data"] == [["", ""], ["", ""], ["", ""]]
    store.save_sheet(s["id"], u["id"], "Бюджет", 2, 2, [["10", "20"], ["=A1+B1", ""]])
    got = store.get_sheet(s["id"], u["id"])
    assert got["data"] == [["10", "20"], ["=A1+B1", ""]] and got["rows"] == 2
    assert [x["id"] for x in store.list_sheets(u["id"])] == [s["id"]]
    # чужую таблицу не видно
    other = store.create_user("other2", "secret1")
    assert store.get_sheet(s["id"], other["id"]) is None
    store.delete_sheet(s["id"], u["id"])
    assert store.list_sheets(u["id"]) == []
