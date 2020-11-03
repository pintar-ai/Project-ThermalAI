from flask import Flask, jsonify, render_template, request, abort, redirect, url_for, flash
from flask_mail import Mail,  Message
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, not_, null
from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy_utils import PhoneNumber
from datetime import date, timedelta, datetime
from io import BytesIO
from dateutil import tz
import phonenumbers
import qrcode
import base64
import bcrypt
import traceback
import secrets

qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=10,
    border=4,
)

app = Flask(__name__)
app.config.from_object("config.Config")
db = SQLAlchemy(app)
mail = Mail(app)

import flask_login
login_manager = flask_login.LoginManager()
login_manager.login_view = 'portal'
login_manager.login_message_category = "info"
login_manager.init_app(app)

class User(flask_login.UserMixin):
    pass

# region Postgres DB Structure
class Users(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password = db.Column(db.LargeBinary(128), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False)

    def __init__(self, name, email, password, is_admin=False):
        self.name = name
        self.email = email
        salt = bcrypt.gensalt()
        self.password = bcrypt.hashpw(password.encode('utf-8'), salt)
        self.is_admin = is_admin


class Device(db.Model):
    __tablename__ = 'device'

    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    owner = db.Column(db.Integer, db.ForeignKey(Users.id, ondelete='SET NULL'), nullable=True)

    def __init__(self, serial_number, name):
        self.serial_number = serial_number
        self.name = name


class Qr(db.Model):
    __tablename__ = 'qr'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    _phone_number = db.Column(db.Unicode(255))
    phone_country_code = db.Column(db.Unicode(8))
    password = db.Column(db.LargeBinary(128), nullable=False)
    token = db.Column(db.String(128), nullable=False)
    is_verified = db.Column(db.Boolean, nullable=False)

    phone_number = db.composite(
        PhoneNumber,
        _phone_number,
        phone_country_code
    )

    def __init__(self, name, email, phone_number, password, token):
        self.name = name
        self.email = email
        self.phone_number = phone_number
        salt = bcrypt.gensalt()
        self.password = bcrypt.hashpw(password.encode('utf-8'), salt)
        self.token = token
        self.is_verified = False


class Record(db.Model):
    __tablename__ = 'record'

    id = db.Column(db.Integer, primary_key=True)
    qr_id = db.Column(db.Integer, db.ForeignKey(Qr.id, ondelete='SET NULL'), nullable=True)
    device_id = db.Column(db.Integer, db.ForeignKey(Device.id, ondelete='SET NULL'), nullable=True)
    temperature = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    def __init__(self, qr_id, device_id, temperature):
        self.qr_id = qr_id
        self.device_id = device_id
        self.temperature = temperature

    @hybrid_property
    def tz_time(self):
        local_zone = tz.gettz('Asia/Kuala_Lumpur')
        return self.timestamp.astimezone(local_zone)
# endregion


# region Portal Section
@app.route("/contact_us")
def contact_us():
    return render_template('contact_us.html')


@app.route("/portal")
def portal():
    try:
        if flask_login.current_user.is_admin:
            return redirect(url_for('admin_dash'))
        elif not flask_login.current_user.is_admin:
            return redirect(url_for('thermal_log'))
    except AttributeError:
        return render_template('login_portal.html')


@login_manager.user_loader
def user_loader(username):
    user_query = Users.query.filter_by(name=username).first()
    if user_query:
        user = User()
        user.id = username
        user.is_admin = user_query.is_admin
        return user
    else:
        return


@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    password = request.form.get('password')
    user_query = Users.query.filter_by(name=username).first()
    if not user_query or not bcrypt.checkpw(password.encode('utf-8'), user_query.password):
        redirect(url_for('portal'))
    else:
        user = User()
        user.id = username
        user.is_admin = user_query.is_admin
        return user


@app.route("/validate_portal", methods=['POST'])
def validate_portal():
    username = request.form.get('username')
    password = request.form.get('password')
    remember = True if request.form.get('remember') else False

    user_data = Users.query.filter_by(name=username).first()

    # check if user actually exists
    # take the user supplied password, hash it, and compare it to the hashed password in database
    if not user_data or not bcrypt.checkpw(password.encode('utf-8'), user_data.password):
        flash('Please check your login details and try again.', category="warning")
        return redirect(url_for('portal', _external=True))  # if user doesn't exist or password is wrong, reload the page

    # if the above check passes, then we know the user has the right credentials
    user = User()
    user.id = username
    flask_login.login_user(user)
    if user_data.is_admin:
        return redirect(url_for('admin_dash'))
    else:
        return redirect(url_for('thermal_log'))


@app.route('/admin_dash')
@flask_login.login_required
def admin_dash():
    if not flask_login.current_user.is_admin:
        return render_template("user_dash.html")

    return render_template("admin_dash.html")


@app.route('/user_count')
@flask_login.login_required
def user_count():
    count_user = db.session.query(Users).filter_by(is_admin=False).count()
    count_admin = db.session.query(Users).filter_by(is_admin=True).count()

    return jsonify({'count_user': count_user, 'count_admin': count_admin}), 200


@app.route('/device_count')
@flask_login.login_required
def device_count():
    count_active = db.session.query(Device).filter(Device.owner.isnot(None)).count()
    count_dormant = db.session.query(Device).filter(Device.owner.is_(None)).count()

    return jsonify({'count_active': count_active, 'count_dormant': count_dormant}), 200


@app.route('/visitor_count')
@flask_login.login_required
def visitor_count():
    local_zone = tz.gettz('Asia/Kuala_Lumpur')
    my_zone = tz.gettz()
    user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
    owned_device = db.session.query(Device.id).filter_by(owner=user_data.id)
    date_to_show = db.session.query(func.max(Record.timestamp)).filter(Record.device_id.in_(owned_device)).scalar()
    label = []
    count = []
    if date_to_show:
        data_user = db.session.query(Record, Qr, Device).join(Qr).join(Device).filter_by(owner=user_data.id)
        latest_day = datetime(date_to_show.year, date_to_show.month, date_to_show.day, tzinfo=tz.tzutc()).astimezone(my_zone)
        latest_day = latest_day.replace(tzinfo=local_zone)
        for day in range(7):  #count record start with least day in week so we get 7 days count
            start = latest_day - timedelta(6-day)
            start = start.replace(tzinfo=local_zone)
            end = start + timedelta(1)
            end = end.replace(tzinfo=local_zone)
            record_date = start.strftime('%d/%m/%Y')
            label.append(record_date)
            record_count = data_user.filter(and_(Record.timestamp >= start.astimezone(), Record.timestamp <= end.astimezone())).count()
            count.append(record_count)
    return jsonify({'label': label, 'count': count}), 200


@app.route('/user_list')
@flask_login.login_required
def user_list():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))
    data_user = db.session.query(Users).order_by(Users.is_admin).all()
    return render_template('user_list.html', users=data_user, username=flask_login.current_user.id)


@app.route('/delete_user', methods=['POST'])
@flask_login.login_required
def delete_user():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))

    username = request.form.get('username')

    user_exist = Users.query.filter_by(name=username).first()
    if user_exist:
        db.session.delete(user_exist)
        db.session.commit()
        flash('You were successfully delete user ' + username, category="success")
    else:
        flash('User ' + username + ' is not exist', category="danger")
    return redirect(url_for('user_list'))


@app.route('/update_user', methods=['POST'])
@flask_login.login_required
def update_user():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))

    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    repassword = request.form.get('repassword')
    privilage = True if request.form.get('privilage') == "True" else False

    if password == repassword:
        edit_user = Users.query.filter_by(name=username).first()
        if edit_user:
            salt = bcrypt.gensalt()
            edit_user.password = bcrypt.hashpw(password.encode('utf-8'), salt)
            edit_user.email = email
            edit_user.is_admin = privilage
            db.session.commit()
            flash('You were successfully update detail for user ' + username, category="success")
        else:
            flash(username + ' not found', category="danger")
    else:
        flash('Password not matched. Try again.', category="danger")
    return redirect(url_for('user_list'))


@app.route('/create_user', methods=['POST'])
@flask_login.login_required
def create_user():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))

    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    privilage = True if request.form.get('privilage') == "True" else False

    user_exist = Users.query.filter_by(name=username).first()
    email_exist = Users.query.filter_by(email=email).first()
    if user_exist:
        flash('User ' + username + ' already exist', category="danger")
    elif email_exist:
        flash('Email ' + email + ' already exist', category="danger")
    else:
        db.session.add(Users(name=username, email=email, password=password, is_admin=privilage))
        db.session.commit()
        flash('You were successfully adding user ' + username, category="success")
    return redirect(url_for('user_list'))


@app.route('/user_profile')
@flask_login.login_required
def user_profile():
    user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
    if user_data.is_admin:
        privilagelabel = "Admin"
        template = 'admin_profile.html'
    else:
        privilagelabel = "User"
        template = 'user_profile.html'

    return render_template(template, username=user_data.name, privilagel=privilagelabel, privilage=user_data.is_admin)


@app.route('/update_password', methods=['POST'])
@flask_login.login_required
def update_password():
    password = request.form.get('password')
    repassword = request.form.get('repassword')
    if password == repassword:
        edit_user = Users.query.filter_by(name=flask_login.current_user.id).first()
        if edit_user:
            salt = bcrypt.gensalt()
            edit_user.password = bcrypt.hashpw(password.encode('utf-8'), salt)
            db.session.commit()
            flash('You were successfully update detail for user ' + flask_login.current_user.id, category="success")
        else:
            flash(flask_login.current_user.id + ' not found', category="danger")
    else:
        flash('Password not matched. Try again.', category="danger")
    return redirect(url_for('user_profile'))


@app.route('/device_list')
@flask_login.login_required
def device_list():
    user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
    if user_data.is_admin:
        active_device = db.session.query(Device, Users).join(Device).order_by(Device.owner).all()
        dormant_device = db.session.query(Device).filter(Device.owner.is_(None)).all()
        template = 'device_list.html'
    else:
        active_device = db.session.query(Device, Users).join(Device).filter_by(owner=user_data.id).all()
        dormant_device = []
        template = 'user_device.html'
    list_data = []
    
    for device in active_device:
        list_data.append({"serial_number": device.Device.serial_number, "name": device.Device.name, "owner": device.Users.name})
    
    for device in dormant_device:
        list_data.append({"serial_number": device.serial_number, "name": device.name, "owner": "None"})
    return render_template(template, devices=list_data, username=flask_login.current_user.id)


@app.route('/delete_device', methods=['POST'])
@flask_login.login_required
def delete_device():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))

    device_serial = request.form.get('serial_number')

    device_exist = Device.query.filter_by(serial_number=device_serial).first()
    if device_exist:
        db.session.delete(device_exist)
        db.session.commit()
        flash('You were successfully delete device ' + device_serial, category="success")
    else:
        flash('Device ' + device_serial + ' is not exist', category="danger")
    return redirect(url_for('device_list'))


@app.route('/logout_device', methods=['POST'])
@flask_login.login_required
def logout_device():
    device_serial = request.form.get('serial_number')
    device_exist = Device.query.filter_by(serial_number=device_serial).first()
    if device_exist:
        user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
        if user_data.is_admin or (device_exist.owner is user_data.id):
            device_exist.owner = null()
            db.session.commit()
            flash('You were successfully logout device ' + device_serial, category="success")
        else:
            flash('Device protected', category="danger")
    else:
        flash('Device ' + device_serial + ' is not exist', category="danger")
    return redirect(url_for('device_list'))


@app.route('/update_device', methods=['POST'])
@flask_login.login_required
def update_device():
    device_serial = request.form.get('serial_number')
    device_name = request.form.get('name')

    device_exist = Device.query.filter_by(serial_number=device_serial).first()
    if device_exist:
        #Filter by user privilage
        user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
        if not user_data.is_admin:
            if not device_exist.owner is user_data.id:
                flash('you have no access to this device', category="danger")
                return redirect(url_for('device_list'))
        device_exist.name = device_name
        db.session.commit()
        flash('You were successfully update detail for device ' + device_serial, category="success")
    else:
        flash(device_serial + ' not found', category="danger")
    return redirect(url_for('device_list'))


@app.route('/create_device', methods=['POST'])
@flask_login.login_required
def create_device():
    if not flask_login.current_user.is_admin:
        return redirect(url_for('admin_dash'))

    device_serial = request.form.get('serial_number')
    device_name = request.form.get('name')

    device_exist = Device.query.filter_by(serial_number=device_serial).first()
    if device_exist:
        flash('Device ' + device_serial + ' already exist', category="danger")
    else:
        db.session.add(Device(serial_number=device_serial, name=device_name))
        db.session.commit()
        flash('You were successfully adding Device ' + device_serial, category="success")
    return redirect(url_for('device_list'))


@app.route('/thermal_log', methods=['GET', 'POST'])
@flask_login.login_required
def thermal_log():
    mode = request.args.get("mode") if request.args.get("mode") else "day"
    need_json = True if request.args.get("need_json") == "true" else False
    
    # today = date.today()
    utc_zone = tz.gettz('UTC')
    local_zone = tz.gettz('Asia/Kuala_Lumpur')
    my_zone = tz.gettz()
    today = datetime.utcnow().date()

    #Filter by user privilage
    user_data = Users.query.filter_by(name=flask_login.current_user.id).first()
    if user_data.is_admin:
        date_to_show = datetime.strptime(request.args.get("date_pick"), '%d/%m/%Y') if request.args.get("date_pick") else db.session.query(func.max(Record.timestamp)).scalar().astimezone(local_zone)
        data_user = db.session.query(Record, Qr, Device).join(Qr).join(Device).filter()
        template = 'thermal_log.html'
    else:
        owned_device = db.session.query(Device.id).filter_by(owner=user_data.id)
        date_to_show = datetime.strptime(request.args.get("date_pick"), '%d/%m/%Y') if request.args.get("date_pick") else db.session.query(func.max(Record.timestamp)).filter(Record.device_id.in_(owned_device)).scalar().astimezone(local_zone)
        data_user = db.session.query(Record, Qr, Device).join(Qr).join(Device).filter_by(owner=user_data.id)
        template = 'user_log.html'
    print("date requested :", date_to_show)

    if date_to_show:
        start = datetime(date_to_show.year, date_to_show.month, date_to_show.day, tzinfo=tz.tzutc()).astimezone(my_zone)
        start = start.replace(tzinfo=local_zone)
        if mode == "day":
            end = start + timedelta(1)
            end = end.replace(tzinfo=local_zone)
        elif mode == "week":
            end = start + timedelta(7)
            end = end.replace(tzinfo=local_zone)
        elif mode == "month":
            end = start + timedelta(30)
            end = end.replace(tzinfo=local_zone)
        #print("local time", start, end)
        #print("utc time", start.astimezone(utc_zone), end.astimezone(utc_zone))
        record_on_day = data_user.filter(and_(Record.timestamp >= start.astimezone(), Record.timestamp <= end.astimezone())).order_by(Record.timestamp.asc())
        #print("show query filter:")
        #for data1 in record_on_day:
        #    print(data1.Record.timestamp, data1.Record.tz_time)
        if need_json:
            data_send = []
            for data in record_on_day:
                timestamp = data.Record.tz_time.strftime('%H:%M:%S %d-%m-%Y')
                data_temp = {"name": data.Qr.name, "phone": data.Qr.phone_number.e164, "device": data.Device.name, "temperature": data.Record.temperature, "timestamp": timestamp}
                data_send.append(data_temp)
            return jsonify({'result': data_send, 'date_to_show': date_to_show})
        else:
            return render_template(template, show_record=record_on_day, date_to_show=date_to_show)
    else:
        return render_template(template, show_record=[], date_to_show=date.today())


@app.route('/logout')
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return redirect(url_for('portal'))
# endregion


# region QR ID section
@app.route("/sign_up")
def sign_up():
    return render_template('sign_up.html')


@app.route("/term_condition")
def term_condition():
    return render_template('term_condition.html')


@app.route("/")
def login():
    return render_template("login_qr.html")


@app.route("/reg", methods=['POST'])
def reg():
    username = request.form['username']
    phone_number = request.form['phone_number']
    email = request.form['email']
    password = request.form['password']

    #check phone number if already exist
    user_check_phone = Qr.query.filter_by(phone_number=PhoneNumber(phone_number, 'MY')).first()
    if user_check_phone:
        if user_check_phone.is_verified:
            flash("Phone Number already registered", category="danger")
            return redirect(url_for('sign_up'))
        
    
    #check email if already exist
    user_check_email = Qr.query.filter_by(email=email).first()
    if user_check_email:
        if user_check_email.is_verified:
            flash("Email already registered", category="danger")
            return redirect(url_for('sign_up'))
        
    if user_check_phone and user_check_email:
        if user_check_email.is_verified:
            flash("Email & Phone Number already registered", category="danger")
            return redirect(url_for('sign_up'))
        else:
            salt = bcrypt.gensalt()
            user_check_phone.password = bcrypt.hashpw(password.encode('utf-8'), salt)
            user_check_phone.token = secrets.token_urlsafe(90) 
    elif user_check_phone:
        user_check_phone.email = email
        salt = bcrypt.gensalt()
        user_check_phone.password = bcrypt.hashpw(password.encode('utf-8'), salt)
        user_check_phone.token = secrets.token_urlsafe(90) 
    elif user_check_email:
        user_check_email.phone_number = PhoneNumber(phone_number, 'MY')
        salt = bcrypt.gensalt()
        user_check_email.password = bcrypt.hashpw(password.encode('utf-8'), salt)
        user_check_email.token = secrets.token_urlsafe(90)
    else:
        db.session.add(Qr(name=username, email=email, phone_number=PhoneNumber(phone_number, 'MY'), password=password, token=secrets.token_urlsafe(90)))
    
    db.session.commit()
    qr_user = Qr.query.filter_by(email=email).first()
    verify_link = url_for('verify_qr', _external=True)+'?token='+qr_user.token
    msg = Message(subject="Verify Your QR Id Account", sender='noreply@pintar-ai.my', recipients=[qr_user.email])
    msg.html = render_template('mail_verify.html', username=username, verify_link=verify_link)
    mail.send(msg)
    return render_template('thank_you.html')


@app.route("/qr_login", methods=['POST'])
def qr_login():
    phone_email = request.form['phone_email']
    password = request.form['password']
    for match in phonenumbers.PhoneNumberMatcher(phone_email, 'MY'):
        phone_number = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        qr_user = Qr.query.filter_by(phone_number=PhoneNumber(phone_number, 'MY')).first()
        if qr_user:
            if not bcrypt.checkpw(password.encode('utf-8'), qr_user.password):
                flash("Wrong password", category="danger")
                return redirect(url_for('login'))
            if not qr_user.is_verified:
                flash("Please verify your account", category="danger")
                return redirect(url_for('login'))
            img = string_to_qr("qr_id/" + qr_user.phone_number.e164)
            return serve_pil_image(img)
    qr_user = Qr.query.filter_by(email=phone_email).first()
    if qr_user:
        if not bcrypt.checkpw(password.encode('utf-8'), qr_user.password):
            flash("Wrong password", category="danger")
            return redirect(url_for('login'))
        if not qr_user.is_verified:
            flash("Please verify your account", category="danger")
            return redirect(url_for('login'))
        img = string_to_qr("qr_id/" + qr_user.phone_number.e164)
        return serve_pil_image(img)
    else:
        flash("Phone number or Email hasn't been registered", category="danger")
        return redirect(url_for('login'))


def string_to_qr(string_data):
    qr.clear()
    qr.add_data(string_data)
    qr.make(fit=True)

    return qr.make_image(fill_color="black", back_color="white")


def serve_pil_image(pil_img):
    img_io = BytesIO()
    pil_img.save(img_io, 'JPEG', quality=70)
    img_io.seek(0)
    jpg_as_text = base64.b64encode(img_io.getvalue())
    return render_template('show_qr.html', qr_id=jpg_as_text)


@app.route('/verify_qr')
def verify_qr():
    token = request.args.get("token")
    qr_user = Qr.query.filter_by(token=token).first()
    if qr_user:
        if not qr_user.is_verified:
            qr_user.is_verified = True
            db.session.commit()
        flash("Your account already verified, please login", category="success")
        return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET','POST'])
def forgot_password():
    if request.method == 'POST':
        phone_email = request.form['phone_email']
        for match in phonenumbers.PhoneNumberMatcher(phone_email, 'MY'):
            phone_number = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            qr_user = Qr.query.filter_by(phone_number=PhoneNumber(phone_number, 'MY')).first()
            if qr_user:
                qr_user.token = secrets.token_urlsafe(90)
                db.session.commit()
                reset_link = url_for('reset_password', _external=True)+'?token='+qr_user.token
                msg = Message(subject="Resetting your QR Id password", sender='Pintar-AI', recipients=[qr_user.email])
                msg.html = render_template('mail_reset.html', username=qr_user.name, reset_link=reset_link)
                mail.send(msg)
        qr_user = Qr.query.filter_by(email=phone_email).first()
        if qr_user:
            qr_user.token = secrets.token_urlsafe(90)
            db.session.commit()
            reset_link = url_for('reset_password', _external=True)+'?token='+qr_user.token
            msg = Message(subject="Resetting your QR Id password", sender='Pintar-AI', recipients=[qr_user.email])
            msg.html = render_template('mail_reset.html', username=qr_user.name, reset_link=reset_link)
            mail.send(msg)
        flash("If any account related, we sent link to your email", category="success")
        return redirect(url_for('forgot_password'))
    else:
        return render_template('forgot_password.html')

    
@app.route('/reset_password', methods=['GET','POST'])
def reset_password():
    if request.method == 'POST':
        token = request.form['token']
        new_password = request.form['password']
        qr_user = Qr.query.filter_by(token=token).first()
        if qr_user:
            salt = bcrypt.gensalt()
            qr_user.password = bcrypt.hashpw(new_password.encode('utf-8'), salt)
            db.session.commit()
            flash("Your password already resetted, please login", category="success")
        return redirect(url_for('login'))
    else:
        token = request.args.get("token")
        qr_user = Qr.query.filter_by(token=token).first()
        if qr_user:
            return render_template('reset_password.html', token=token)
        else:
            return redirect(url_for('login'))
# endregion


# region Device API section
def verify_request(json, check_fields):
    if not request.json or not set(check_fields).issubset(json):
        return False, "incomplete field"

    device = Device.query.filter_by(serial_number=json['serial_number']).first()
    if not device:
        return False, "device not registered"
    return True, "pass"


@app.route('/validate_qr', methods=['POST'])
def validate_qr():
    require = ['serial_number', 'qr_id']
    verified, status = verify_request(json=request.json, check_fields=require)
    if not verified:
        jsonify({'failed': status}), 400
    for match in phonenumbers.PhoneNumberMatcher(request.json['qr_id'], 'MY'):
        phone_number = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        qr_user = Qr.query.filter_by(phone_number=PhoneNumber(phone_number, 'MY')).first()
        if qr_user:
            return jsonify({'success': True, 'name': qr_user.name, 'contact': phone_number}), 200
    return jsonify({'failed': 'qr_id not registered'}), 400


@app.route('/record', methods=['POST'])
def record():
    require = ['serial_number', 'qr_id', 'temperature']
    verified, status = verify_request(json=request.json, check_fields=require)
    if not verified:
        jsonify({'failed': status}), 400
    for match in phonenumbers.PhoneNumberMatcher(request.json['qr_id'], 'MY'):
        phone_number = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        qr_user = Qr.query.filter_by(phone_number=PhoneNumber(phone_number, 'MY')).first()
        if qr_user:
            device = Device.query.filter_by(serial_number=request.json['serial_number']).first()
            db.session.add(Record(qr_id=qr_user.id, device_id=device.id, temperature=request.json['temperature']))
            db.session.commit()
            return jsonify({'success': qr_user.name + " recorded"}), 200
    return jsonify({'failed': 'qr_id not registered'}), 400


@app.route('/register_dev', methods=['POST'])
def register_dev():
    require = ['serial_number', 'username', 'password']
    verified, status = verify_request(json=request.json, check_fields=require)
    if not verified:
        jsonify({'failed': status}), 400
    serial_number = request.json['serial_number']
    username = request.json['username']
    password = request.json['password']
    user = Users.query.filter_by(name=username).first()
    device = Device.query.filter_by(serial_number=serial_number).first()

    # check if user actually exists
    # take the user supplied password, hash it, and compare it to the hashed password in database
    if not device or not user or not bcrypt.checkpw(password.encode('utf-8'), user.password):
        return jsonify({'failed': "login fail"}), 400

    device.owner = user.id
    db.session.commit()
    return jsonify({'success': "logged in"}), 200


@app.route('/validate_dev', methods=['POST'])
def validate_dev():
    require = ['serial_number', 'username']
    verified, status = verify_request(json=request.json, check_fields=require)
    if not verified:
        jsonify({'failed': status}), 400
    user = Users.query.filter_by(name=request.json['username']).first()
    if user:
        device = Device.query.filter_by(owner=user.id, serial_number=request.json['serial_number']).first()
        if device:
            return jsonify({'success': "device valid"}), 200
    return jsonify({'failed': "wrong user"}), 400
# endregion
