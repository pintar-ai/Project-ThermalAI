from flask.cli import FlaskGroup

from main_app import app, db, Users, Device


cli = FlaskGroup(app)


@cli.command("create_db")
def create_db():
    db.drop_all()
    db.create_all()
    db.session.commit()


@cli.command("seed_db")
def seed_db():
    db.session.add(Users(name="GMNX", email="azzam.cyber@gmail.com", password="kentang", is_admin=True))
    db.session.add(Device(serial_number="KMZWA88AWAA", name="Pilot Device"))
    db.session.commit()

@cli.command("insert_default")
def seed_db():
    db.session.add(Users(name="admin", email="admin@thermal-ai.my", password="admin", is_admin=True))
    db.session.add(Users(name="test", email="test@thermal-ai.my", password="test", is_admin=False))
    db.session.commit()


if __name__ == "__main__":
    cli()
