from storage import connect, initialize as initialize_schema


def initialize(demo=True):
    initialize_schema(demo=False)
    if not demo:
        return
    with connect() as db:
        if db.execute("SELECT configured OR EXISTS(SELECT 1 FROM services) AS ready FROM profile").fetchone()["ready"]:
            return
        db.execute("UPDATE profile SET name='Тестовый мастер' WHERE id=1")
        db.execute("INSERT INTO services(id,title,price,minutes,instructions) VALUES (1,'Маникюр',2000,90,'')")
        db.execute("INSERT INTO addons(id,service_id,title,price,minutes) VALUES (1,1,'Снятие покрытия',300,15)")
