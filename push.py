import json
import logging
import os
import time
import uuid

import requests
from pywebpush import WebPushException, webpush

from storage import connect


def enqueue(db, message, visit=None, endpoint=None):
    event = uuid.uuid4()
    db.execute("INSERT INTO events VALUES (%s,%s,%s)", (event, visit, message))
    db.execute("""INSERT INTO deliveries(event, endpoint)
                  SELECT %s,endpoint FROM subscriptions WHERE %s::text IS NULL OR endpoint=%s""",
               (event, endpoint, endpoint))


def deliver_one():
    with connect() as db:
        job = db.execute("""SELECT d.*,s.info,e.visit,e.message FROM deliveries d
            JOIN subscriptions s USING(endpoint) JOIN events e ON e.id=d.event
            WHERE accepted IS NULL AND due<=now() ORDER BY due LIMIT 1
            FOR UPDATE OF d SKIP LOCKED""").fetchone()
        if not job:
            return False
        pair = (job["event"], job["endpoint"])
        payload = dict(tag=str(job["event"]), body=job["message"],
                       url="/admin?visit="+str(job["visit"]) if job["visit"] else "/admin")
        try:
            webpush(job["info"],json.dumps(payload),vapid_private_key=os.environ["VAPID_PRIVATE"],
                    vapid_claims={"sub":"mailto:"+os.environ["VAPID_EMAIL"]},timeout=5,ttl=86400)
        except (WebPushException, requests.RequestException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404,410):
                db.execute("DELETE FROM subscriptions WHERE endpoint=%s", (pair[1],))
            else:
                delay = min(3600, 5 * 2 ** min(job["attempts"],10))
                db.execute("""UPDATE deliveries SET attempts=attempts+1,
                    due=now()+make_interval(secs=>%s) WHERE event=%s AND endpoint=%s""",(delay,*pair))
                logging.warning("Отправка отложена, код сервиса %s", status)
        else:
            db.execute("UPDATE deliveries SET accepted=now() WHERE event=%s AND endpoint=%s",pair)
        return True


if __name__ == "__main__":
    while True:
        try:
            if deliver_one():
                continue
        except Exception as exc:
            logging.error("Очередь временно недоступна (%s)", type(exc).__name__)
        time.sleep(2)
