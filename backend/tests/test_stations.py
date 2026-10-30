"""Stations: each station's drivers, cash and deposits, one at a time or all together."""
from app.database import SessionLocal
from app.models import Station
from app.stations import KSA

DAY = "2026-05-20"


def sid(client, code):
    return next(s["id"] for s in client.get("/api/stations").json()["stations"] if s["code"] == code)


def test_every_main_city_has_a_station(client):
    st = client.get("/api/stations").json()["stations"]
    codes = {s["code"] for s in st}
    assert len(st) >= len(KSA) and {"JED", "RUH", "MKH", "DMM", "MED", "TIF", "AHB", "TUU", "GIZ"} <= codes
    jed = next(s for s in st if s["code"] == "JED")
    assert jed["region"] == "Makkah" and jed["drivers"] >= 11  # the demo drivers work at Jeddah


def test_a_report_with_a_site_column_puts_drivers_in_their_station(client):
    text = ("Waybill Number,Collect Method,Actual Received Amount,DA Code,DA Name,Site Code,Site,Collection Operation Time\n"
            f"ST-1,Cash,100.00,S-901,Station Test One,DMM,Dammam,{DAY} 20:00:00\n"
            f"ST-2,Cash,50.00,S-901,Station Test One,DMM,Dammam,{DAY} 20:01:00\n"
            f"ST-3,Cash,70.00,S-902,Station Test Two,NEW9,Hafr New Hub,{DAY} 20:02:00\n")
    up = lambda: {"file": ("report.csv", text.encode(), "text/csv")}  # noqa: E731
    r = client.post("/api/drivers/import", files=up()).json()
    rows = {x["driver_code"]: x for x in r["rows"] if x["status"] != "skipped"}
    assert rows["S-901"]["station"] == "Dammam" and "new station Hafr New" in rows["S-902"]["problems"][0]
    client.post("/api/drivers/import", files=up(), data={"commit": "true"})
    drivers = {d["code"]: d for d in client.get("/api/drivers").json()}
    assert drivers["S-901"]["station_code"] == "DMM" and drivers["S-902"]["station_code"] == "NEW9"
    client.post("/api/collections/import", files=up(), data={"commit": "true"})

    dmm, jed = sid(client, "DMM"), sid(client, "JED")
    # one station at a time: Dammam sees only its own handover and drivers
    day = client.get("/api/collections", params={"date": DAY}, headers={"X-Station": str(dmm)}).json()
    assert [h["driver_code"] for h in day["rows"]] == ["S-901"] and day["totals"]["cash_received"] == 150.0
    assert {d["code"] for d in client.get("/api/drivers", headers={"X-Station": str(dmm)}).json()} == {"S-901"}
    assert all(m["code"] == "S-901" for m in day["missing"]) or day["missing"] == []
    # all stations: both
    assert {h["driver_code"] for h in client.get("/api/collections", params={"date": DAY}).json()["rows"]} >= {"S-901", "S-902"}

    # each station deposits its own cash; with two stations on the day, the station must be chosen
    slip = {"business_date": DAY, "deposit_date": "2026-05-21", "bank": "Coastal National Bank", "slip_ref": "ST-SLIP-1", "amount": 150}
    assert client.post("/api/deposits", json=slip).status_code == 422
    r = client.post("/api/deposits", json=slip, headers={"X-Station": str(dmm)}).json()
    assert r["status"] == "deposited" and r["station"] == "Dammam"
    rows = [x for x in client.get("/api/deposits", params={"end": "2026-05-21", "count": 2}).json()["rows"] if x["date"] == DAY]
    assert {x["station"]: x["status"] for x in rows} == {"Dammam": "deposited", "Hafr New": "overdue"}
    together = [x for x in client.get("/api/deposits", params={"end": "2026-05-21", "count": 2, "days": True}).json()["rows"] if x["date"] == DAY]
    assert together[0]["status"] == "overdue" and together[0]["to_deposit"] == 220.0  # the day is as late as its latest station

    # a station sees nothing of another's money, even by asking for it
    assert client.get("/api/collections", params={"date": DAY}, headers={"X-Station": str(jed)}).json()["rows"] == []
    mine = client.get("/api/deposits", params={"end": "2026-05-21", "count": 2}, headers={"X-Station": str(jed)}).json()["rows"]
    assert all(x["station_id"] == jed for x in mine)

    ov = client.get("/api/stations/overview", params={"date": DAY}).json()
    by = {s["code"]: s for s in ov["stations"]}
    assert by["DMM"]["cash_received"] == 150.0 and by["DMM"]["deposit_status"] == "deposited"
    assert by["NEW9"]["pending"] == 70.0 and ov["totals"]["cash_received"] >= 220.0


def test_a_new_driver_belongs_to_the_station_being_looked_at(client):
    ruh = sid(client, "RUH")
    r = client.post("/api/drivers", json={"code": "S-903", "name": "Riyadh Hand Added"}, headers={"X-Station": str(ruh)}).json()
    assert r["station_code"] == "RUH"
    moved = client.patch(f"/api/drivers/{r['id']}", json={"station_id": sid(client, "JED")}).json()
    assert moved["station_code"] == "JED"


def test_stations_can_be_added_and_renamed(client):
    r = client.post("/api/stations", json={"code": "jed2", "name": "Jeddah South", "city": "Jeddah", "region": "Makkah"})
    assert r.status_code == 201 and r.json()["code"] == "JED2"
    assert client.post("/api/stations", json={"code": "JED2", "name": "Again"}).status_code == 409
    upd = client.put(f"/api/stations/{r.json()['id']}", json={"code": "JED2", "name": "Jeddah South Hub", "city": "Jeddah",
                                                            "region": "Makkah", "active": False}).json()
    assert upd["name"] == "Jeddah South Hub" and upd["active"] is False


def test_old_rows_get_their_drivers_station(client):
    from app import stations
    from app.models import Collection
    with SessionLocal() as db:
        c = db.query(Collection).execution_options(all_stations=True).first()
        keep = c.station_id
        c.station_id = None
        db.commit()
        assert stations.assign_missing(db) >= 1
        assert db.get(Collection, c.id).station_id == keep


def test_ask_can_compare_stations(client):
    from app import ask
    with SessionLocal() as db:
        out = ask.t_stations(db, {"date": "2026-05-20"})
    assert "stations" in out and "totals" in out


def test_old_extra_stations_are_removed_when_unused(client):
    from app import stations
    with SessionLocal() as db:
        db.add(Station(code="SHQ", name="Shaqra", city="Shaqra", region="Riyadh"))
        db.commit()
        stations.ensure_defaults(db)
        assert db.query(Station).filter(Station.code == "SHQ").count() == 0
        assert len(KSA) == 25


def test_a_new_station_from_a_report_gets_its_city_and_region(client):
    from app import stations
    with SessionLocal() as db:
        st = stations.find_or_add(db, "", "Riyadh Al Aarid Station")
        assert (st.code, st.name, st.city, st.region) == ("RUH-AAR", "Riyadh Al Aarid", "Riyadh", "Riyadh")
        assert stations.find_or_add(db, "", "Riyadh Al Aarid Station").id == st.id  # found again next time
        db.rollback()


def test_drivers_without_a_station_can_be_put_in_one(client):
    with SessionLocal() as db:
        from app.models import Collection, Driver
        d = db.query(Driver).filter_by(code="D-102").one()
        d.station_id = None
        for c in db.query(Collection).execution_options(all_stations=True).filter_by(driver_id=d.id):
            c.station_id = None
        db.commit()
    assert client.get("/api/stations").json()["unassigned_drivers"] >= 1
    tif = sid(client, "TIF")
    r = client.post(f"/api/stations/{tif}/adopt").json()
    assert r["drivers"] >= 1 and r["records"] >= 1 and client.get("/api/stations").json()["unassigned_drivers"] == 0
    assert {x["code"]: x for x in client.get("/api/drivers").json()}["D-102"]["station_code"] == "TIF"
    assert client.get("/api/collections", params={"date": DAY}, headers={"X-Station": str(tif)}).status_code == 200
    with SessionLocal() as db:
        from app.models import Collection, Driver
        d = db.query(Driver).filter_by(code="D-102").one()
        d.station_id = sid(client, "JED")
        for c in db.query(Collection).execution_options(all_stations=True).filter_by(driver_id=d.id):
            c.station_id = d.station_id
        db.commit()
