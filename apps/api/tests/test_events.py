from app.events import Broadcaster


def event(event_id: str) -> dict:
    return {"id": event_id, "type": "test", "at": "now", "data": {}}


def test_every_subscriber_receives_every_event():
    broadcaster = Broadcaster()
    first, second = broadcaster.subscribe(), broadcaster.subscribe()
    broadcaster.publish(event("1"))
    assert first.get_nowait()["id"] == "1"
    assert second.get_nowait()["id"] == "1"


def test_reconnecting_client_gets_missed_events():
    broadcaster = Broadcaster()
    for event_id in ("1", "2", "3"):
        broadcaster.publish(event(event_id))
    queue = broadcaster.subscribe(last_event_id="1")
    assert [queue.get_nowait()["id"], queue.get_nowait()["id"]] == ["2", "3"]


def test_unsubscribed_client_stops_receiving():
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)
    broadcaster.publish(event("1"))
    assert queue.empty()
