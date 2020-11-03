from PyQt5 import QtCore, QtGui, QtWidgets, uic
import json
import requests
import imutils
import time
from requests.exceptions import ConnectionError
import sys
import os
import cv2

scriptDir = os.path.dirname(os.path.realpath(__file__))

from ui_main_app import Ui_Form
app = QtWidgets.QApplication(sys.argv)
app.setApplicationName('Thermal-AI')
app.setWindowIcon(QtGui.QIcon(scriptDir + os.path.sep + 'thermalai.png'))

#global param for save PyQt settings
settings = QtCore.QSettings('pintar.ai', 'thermal_ai')
valid_user = settings.value('valid_user')
shouldrun = True

# global param for state server IP
server = "http://178.128.84.171:3000"
#server = "http://localhost:3000"
serial_number = "KMZWA88AWAA"

from thermal_viewer import ThermalReader

# global var for verify QR_Id
_QR_ID = {"id": None, "status": "init"}
_THERMAL_RECORD = {"id": None, "status": "init", "temperature": 0}

# Create dialog for user login
class Login(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(Login, self).__init__(parent)
        self.setWindowTitle("Thermal-AI")
        #self.setWindowIcon(QtGui.QIcon(scriptDir + '/asset-monitoring.png'))
        self.textName = QtWidgets.QLineEdit(self)
        self.textName.setPlaceholderText('Username')
        self.textName.clearFocus()
        self.textPass = QtWidgets.QLineEdit(self)
        self.textPass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.textPass.setPlaceholderText('Password')
        self.textPass.clearFocus()
        self.buttonLogin = QtWidgets.QPushButton('Login', self)
        self.buttonLogin.clicked.connect(self.handleLogin)
        self.buttonLogin.setFocus()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.textName)
        layout.addWidget(self.textPass)
        layout.addWidget(self.buttonLogin)

    def handleLogin(self):
        if (self.register(self.textName.text(), self.textPass.text())):
            settings.setValue('username', str(self.textName.text()))
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(
                self, 'Error', self.message)

    def register(self, username, password):
        global settings
        url = server + "/register_dev"

        payload = "{\n\t\"serial_number\":\"%s\",\n\t\"username\":\"%s\",\n\t\"password\":\"%s\"\n}" % (str(serial_number), str(username), str(password))
        headers = {'Content-Type': "application/json", 'cache-control': "no-cache"}

        try:
            response = requests.request("POST", url, data=payload, headers=headers)
            if response.status_code == 200:
                settings.setValue('valid_user', str(username))
                return True
            else:
                self.message = "Bad user or password"
                return False
        except ConnectionError:
            self.message = "Check your network"
            return False

# Create a class for our main window
class Main(QtWidgets.QWidget):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)
        
        # This is always the same
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        self.ui.exit_button.clicked.connect(self.exit_window)

        # Net Thread
        self.netthread = NetThread()
        self.netthread.visitor_status.connect(self.set_visitor)
        self.netthread.newstatus.connect(self.set_status)
        self.netthread.start()
        # Video stream
        self.video = VideoThread(0)
        self.video.newimage.connect(self.set_frame)
        self.video.newstatus.connect(self.set_status)
        self.video.visitor_status.connect(self.set_visitor)
        self.video.start()

        self.show()

    @QtCore.pyqtSlot(QtGui.QImage)
    def set_frame(self, frame):
        pixmap = QtGui.QPixmap.fromImage(frame)
        self.ui.video_label.setPixmap(pixmap)

    @QtCore.pyqtSlot(str)
    def set_status(self, status):
        self.ui.status_label.setText(str(status))

    @QtCore.pyqtSlot(dict)
    def set_visitor(self, visitor):
        if "name" in visitor:
            self.ui.name_label.setText(str(visitor["name"]))
        if "contact" in visitor:
            self.ui.contact_label.setText(str(visitor["contact"]))
        if "temperature" in visitor:
            self.ui.temperature_label.setText(str(visitor["temperature"]))
            if "date" in visitor:
                self.ui.date_label.setText(str(visitor["date"]))
            else:
                self.ui.date_label.setText(time.strftime("%d-%m-%Y")) 

    def exit_window(self):
        global shouldrun
        shouldrun = False
        while (not self.netthread.is_stopped) and (not self.video.is_stopped):
            time.sleep(0.1)
        if self.netthread.isRunning():
            self.netthread.terminate()
            self.netthread.wait(1000)
        if self.video.isRunning():
            self.video.terminate()
            self.video.wait(1000)
        try:
            self.close()
        except:
            print('Error: ', sys.exc_info()[0])

class VideoThread(QtCore.QThread):
    newimage = QtCore.pyqtSignal(QtGui.QImage)
    newstatus = QtCore.pyqtSignal(str)
    visitor_status = QtCore.pyqtSignal(dict)
    # Const from calibrate result
    ZOOM_WIDTH = 660  # webcam adjust width. using actual frame size in VLC then compare it
    CROP_Y = 82  # upper to start crop
    CROP_X = 124  # left to start crop

    def __init__(self, address):
        super(VideoThread, self).__init__()
        self.video_address = address
        self.is_stopped = True
        self.thermal_reader = ThermalReader(source=self.video_address, skip=3, low_temp=35, high_temp=37)
        thermal_ready = self.thermal_reader.init_lepton()
        while not thermal_ready:
            thermal_ready = self.thermal_reader.init_lepton()
            print("Please check thermal camera connection")
            time.sleep(2.0)

    def run(self):
        self.is_stopped = False
        while shouldrun:
            self.phase = "qr"
            self.qr_reader()
            if not shouldrun:
                break
            time.sleep(0.1)
            self.thermal_reader.start()
            print("thermal camera started")
            instruction = False
            while self.phase == "thermal":
                thermal_frame = self.thermal_reader.thermal_frame
                visitor_temperature = self.thermal_reader.temperature
                if not thermal_frame is None:
                    thermal_frame = cv2.cvtColor(thermal_frame, cv2.COLOR_BGR2RGB)
                    convertToQtFormat = QtGui.QImage(thermal_frame.data, thermal_frame.shape[1], thermal_frame.shape[0], QtGui.QImage.Format_RGB888)
                    p = convertToQtFormat.scaled(800, 600, QtCore.Qt.KeepAspectRatio)
                    self.newimage.emit(p)
                    time.sleep(0.1)
                if not instruction:
                    self.newstatus.emit("Please move your face to match the box")
                if visitor_temperature:
                    print("visitor IOU acceptable")
                    self.visitor_status.emit({"temperature": visitor_temperature})
                    self.thermal_reader.stop()
                    _THERMAL_RECORD["temperature"] = visitor_temperature
                    _THERMAL_RECORD["status"] = None
                    time.sleep(1.0)
                    if _THERMAL_RECORD["status"] is True:
                        self.newstatus.emit("Your data has been recorded")
                        self.phase = "qr"
                    elif _THERMAL_RECORD["status"] is False:
                        self.newstatus.emit("Can't connect to server")
                        _THERMAL_RECORD["status"] = "init"
                    
            time.sleep(2.0)
            self.visitor_status.emit({"name": "No Data", "contact": "+xxx-xxx-xxx", "temperature": 0, "date": 0})
            self.newstatus.emit("Please Scan Your QR Id")
            thermal_frame = None
            visitor_temperature = None
        self.thermal_reader.stop()
        self.is_stopped = True

    def qr_reader(self):
        cam = cv2.VideoCapture(self.video_address)
        detector = cv2.QRCodeDetector()
        data = ""
        new_data = ""
        while self.phase == "qr" and shouldrun:
            ret, img = cam.read()
            if not ret:
                time.sleep(0.1)
                continue
            frame = imutils.resize(img, width=self.ZOOM_WIDTH)
            webcam_frame = frame[self.CROP_Y:self.CROP_Y + 300, self.CROP_X:self.CROP_X + 400]
            webcam_frame = cv2.cvtColor(webcam_frame, cv2.COLOR_BGR2RGB)
            try:
                new_data, bbox, _ = detector.detectAndDecode(webcam_frame)
            except:
                continue
            if data != new_data and new_data:
                self.newstatus.emit("checking qr_id")
                data = new_data
                _QR_ID["id"] = data
                _QR_ID["status"] = None
            if _QR_ID["status"] is False:
                print("QR_Id not registered " + _QR_ID["id"])
                self.newstatus.emit("Please Scan Your QR Id")
                _QR_ID["status"] = "init"
            elif _QR_ID["status"] is True:
                self.newstatus.emit("Start to read your temperature")
                self.phase = "thermal"
                _QR_ID["status"] = "init"
                _THERMAL_RECORD["id"] = _QR_ID["id"]
            webcam_frame = cv2.flip(webcam_frame, 1)
            convertToQtFormat = QtGui.QImage(webcam_frame.data, webcam_frame.shape[1], webcam_frame.shape[0], QtGui.QImage.Format_RGB888)
            p = convertToQtFormat.scaled(800, 600, QtCore.Qt.KeepAspectRatio)
            self.newimage.emit(p)
        cam.release()

class NetThread(QtCore.QThread):
    newstatus = QtCore.pyqtSignal(str)
    visitor_status = QtCore.pyqtSignal(dict)

    def __init__(self):
        super(NetThread, self).__init__()
        self.validate_url = server + "/validate_qr"
        self.record_url = server + "/record"
        self.is_stopped = True

    def run(self):
        self.is_stopped = False
        while shouldrun:
            if _QR_ID["status"] is None and _QR_ID["id"]:
                payload = "{\n\t\"serial_number\":\"%s\"\n, \n\t\"qr_id\":\"%s\"\n}" % (str(serial_number), str(_QR_ID["id"]))
                valid, data = self.upload(self.validate_url, payload)
                _QR_ID["status"] = valid
                if valid:
                    self.visitor_status.emit(data)
            if _THERMAL_RECORD["status"] is None and _THERMAL_RECORD["id"]:
                payload = "{\n\t\"serial_number\":\"%s\"\n, \n\t\"qr_id\":\"%s\"\n, \n\t\"temperature\":\"%s\"\n}" % (str(serial_number), str(_THERMAL_RECORD["id"]), str(_THERMAL_RECORD["temperature"]))
                valid, data = self.upload(self.record_url, payload)
                _THERMAL_RECORD["status"] = valid
        self.is_stopped = True

    def upload(self, url, payload):
        headers = {
            'Content-Type': "application/json",
            'cache-control': "no-cache"
            }
        try:
            response = requests.request("POST", url, data=payload, headers=headers)
            data = response.json()
            if 'success' in data:
                return True, data
            else:
                return False, data
        except ConnectionError:
            self.newstatus.emit("Can't Connect to server")
            return None, {}


def validate(valid_user):
    if not valid_user:
        return False
    url = server + "/validate_dev"

    payload = "{\n\t\"serial_number\":\"%s\"\n, \n\t\"username\":\"%s\"\n}" % (str(serial_number), str(valid_user))
    headers = {
        'Content-Type': "application/json",
        'cache-control': "no-cache"
        }

    response = requests.request("POST", url, data=payload, headers=headers)
    data = response.json()
    if 'success' in data:
        return True
    else:
        return False

if __name__ == "__main__":
    login = Login()
    isvalid = False
    try:
        isvalid = validate(valid_user)
    except ConnectionError:
        QtWidgets.QMessageBox.warning(login, 'Error', "Can't Connect to server")
        quit()
    if isvalid or login.exec_() == QtWidgets.QDialog.Accepted:
        shouldrun = True
        window = Main()
        window.show()

        app.lastWindowClosed.connect(app.quit)

        # execute application
        sys.exit(app.exec_())
