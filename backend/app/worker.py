"""Background worker: SLA scanner, intake pollers, outbox. Run as a separate process:  python -m app.worker"""
import logging, time
from app.config import get_settings
from app.database import SessionLocal, Base, engine
from app.security import utcnow
from app.services import sla, intake_msg91, intake_email, outbox

log = logging.getLogger("skyking.worker")


def tick(last_reconcile=[0.0]):
    db = SessionLocal()
    try:
        res = {"sla": sla.scan(db)}
        for name, fn in (("msg91", lambda: intake_msg91.sync(db)), ("email", lambda: intake_email.poll_imap(db)),
                         ("outbox", lambda: outbox.deliver(db))):
            try: res[name] = fn()
            except Exception:
                db.rollback(); log.exception("%s failed", name); res[name] = "error"
        if time.time() - last_reconcile[0] > 86400:
            last_reconcile[0] = time.time()
            issues = sla.reconcile(db)
            if issues:
                from app.services import notify
                notify.to_admins(db, f"Daily integrity check found {len(issues)} issue(s): {issues[:3]}"); db.commit()
        log.info("tick %s", res)
        return res
    finally:
        db.close()


def main():
    if get_settings().APP_ENV != "production":
        Base.metadata.create_all(engine)
    interval = get_settings().WORKER_INTERVAL_SECONDS
    log.info("worker started, interval=%ss", interval)
    while True:
        try: tick()
        except Exception: log.exception("tick failed")
        # heartbeat: a monitor should alert when this log line stops appearing
        log.info("HEARTBEAT %s", utcnow().isoformat())
        time.sleep(interval)


if __name__ == "__main__":
    main()
