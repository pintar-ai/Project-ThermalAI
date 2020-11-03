# import the necessary packages
from trackableobject import TrackableObject
from imutils.video import FPS
import numpy as np
import time
import cv2
import threading
from Webcam_VideoDetector import FaceDetect
from uvctypes import *
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
import platform
_THREADING = {"stopEvent": threading.Event(), "shouldrun": True, "thread": threading.Thread(target="")}
BUF_SIZE = 2
q = Queue(BUF_SIZE)

def py_frame_callback(frame, userptr):
    array_pointer = cast(frame.contents.data, POINTER(c_uint16 * (frame.contents.width * frame.contents.height)))
    data = np.frombuffer(
        array_pointer.contents, dtype=np.dtype(np.uint16)
    ).reshape(
        frame.contents.height, frame.contents.width
    ) # no copy

    # data = np.fromiter(
    #   frame.contents.data, dtype=np.dtype(np.uint8), count=frame.contents.data_bytes
    # ).reshape(
    #   frame.contents.height, frame.contents.width, 2
    # ) # copy

    if frame.contents.data_bytes != (2 * frame.contents.width * frame.contents.height):
        return

    if not q.full():
        q.put(data)

PTR_PY_FRAME_CALLBACK = CFUNCTYPE(None, POINTER(uvc_frame), c_void_p)(py_frame_callback)

def ktof(val):
    return (1.8 * ktoc(val) + 32.0)

def ktoc(val):
    return (val - 27315) / 100.0

def raw_to_8bit(data):
    cv2.normalize(data, data, 0, 65535, cv2.NORM_MINMAX)
    np.right_shift(data, 8, data)
    heatmap = cv2.cvtColor(np.uint8(data), cv2.COLOR_GRAY2RGB) #original grayscale
    #heatmap = cv2.cvtColor(heatmap, cv2.COLOR_RGB2BGR)
    heatmap = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)
    return heatmap

class ThermalReader:
    # Const from region to read temp
    CROP_Y = 52  # upper to start crop
    CROP_X = 98  # left to start crop
    SIZE = 200 #box size
    TEMP_BBOX = [CROP_X, CROP_Y, CROP_X + SIZE, CROP_Y + SIZE]

    def __init__(self, source="", skip=1, low_temp=34, high_temp=37):
        self.face_detector = FaceDetect(source=source, skip=skip)

        # Temperature threshold to change bbox color
        self.low_temp = low_temp
        self.high_temp = high_temp

        # Lepton Variable
        self.ctx = POINTER(uvc_context)()
        self.dev = POINTER(uvc_device)()
        self.devh = POINTER(uvc_device_handle)()
        self.ctrl = uvc_stream_ctrl()

        self.thermal_frame = None
        self.temperature = None

    def bb_intersection_over_union(self, boxA, boxB):
        # determine the (x, y)-coordinates of the intersection rectangle
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        # compute the area of intersection rectangle
        interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)
        # compute the area of both the prediction and ground-truth
        # rectangles
        boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
        boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)
        # compute the intersection over union by taking the intersection
        # area and dividing it by the sum of prediction + ground-truth
        # areas - the interesection area
        iou = interArea / float(boxAArea + boxBArea - interArea)
        # return the intersection over union value
        return iou

    def init_lepton(self):
        res = libuvc.uvc_init(byref(self.ctx), 0)
        if res < 0:
            print("uvc_init error")
            return False

        res = libuvc.uvc_find_device(self.ctx, byref(self.dev), PT_USB_VID, PT_USB_PID, 0)
        if res < 0:
            print("uvc_find_device error")
            return False

        res = libuvc.uvc_open(self.dev, byref(self.devh))
        if res < 0:
            print("uvc_open error")
            return False

        print("device opened!")

        print_device_info(self.devh)
        print_device_formats(self.devh)

        frame_formats = uvc_get_frame_formats_by_guid(self.devh, VS_FMT_GUID_Y16)
        if len(frame_formats) == 0:
            print("device does not support Y16")
            return False

        libuvc.uvc_get_stream_ctrl_format_size(self.devh, byref(self.ctrl), UVC_FRAME_FORMAT_Y16,
            frame_formats[0].wWidth, frame_formats[0].wHeight, int(1e7 / frame_formats[0].dwDefaultFrameInterval)
        )
        return True

    def start(self):
        _THREADING["shouldrun"] = True
        _THREADING["stopEvent"] = threading.Event()
        _THREADING["thread"] = threading.Thread(target=self.detect_temp)
        _THREADING["thread"].start()

    def detect_temp(self):
        self.face_detector.start()
        res = libuvc.uvc_start_streaming(self.devh, byref(self.ctrl), PTR_PY_FRAME_CALLBACK, None, 0)
        if res < 0:
            print("uvc_start_streaming failed: {0}".format(res))
        trackableObjects = {}
        # loop over frames from the video stream
        while _THREADING["shouldrun"]:
            detector_ready = self.face_detector.isstarted()
            # grab frame from each camera
            data = q.get(True, 500)
            if data is None or not detector_ready:
                time.sleep(1.0)
                continue
            data = cv2.resize(data[:,:], (400, 300))
            raw_data = data.copy()
            lepton_frame = raw_to_8bit(data)
            lepton_frame = cv2.flip(lepton_frame, 1)
            
            # use the centroid tracker to associate the (1) old object
            # centroids with (2) the newly computed object centroids
            objects = self.face_detector.objects.copy()
            obj_rects = self.face_detector.obj_rects.copy()

            # loop over the tracked objects
            for (objectID, centroid) in objects.items():
                # check to see if a trackable object exists for the current
                # object ID
                to = trackableObjects.get(objectID, None)

                # compute max temp for ROI
                (startX, startY, endX, endY) = obj_rects[objectID]
                if startX < 0:
                    startX = 0
                if startY < 0:
                    startY = 0
                if endX > 400:
                    endX = 400
                if endY > 300:
                    endY = 300
                max_temp = np.max(raw_data[startY:endY, startX:endX])
                val = ktoc(max_temp)
                temp = "Max {0:.1f} degC".format(val)
                color = (0, 255, 0)
                if self.low_temp < val < self.high_temp:
                    color = (0, 255, 255)
                elif val >= 37:
                    color = (0, 0, 255)

                # if there is no existing trackable object, create one
                if to is None:
                    to = TrackableObject(objectID, centroid)

                # otherwise, there is a trackable object so we can utilize it
                # to determine direction
                else:
                    # the difference between the y-coordinate of the *current*
                    # centroid and the mean of *previous* centroids will tell
                    # us in which direction the object is moving (negative for
                    # 'up' and positive for 'down')
                    y = [c[1] for c in to.centroids]
                    direction = centroid[1] - np.mean(y)
                    to.centroids.append(centroid)

                # store the trackable object in our dictionary
                trackableObjects[objectID] = to

                # draw both the ID of the object and the centroid of the
                # object on the output frame
                text = "ID {}".format(objectID)
                #cv2.putText(lepton_frame, text, (centroid[0] - 10, centroid[1] - 10),
                #    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
                cv2.circle(lepton_frame, (centroid[0], centroid[1]), 4, color, -1)
                cv2.rectangle(lepton_frame, (startX, startY), (endX, endY),
                    color, 2)
                cv2.putText(lepton_frame, temp, (startX, startY - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2)

                #Determine if face close enough to temp camera (improve reading accuracy)
                iou = self.bb_intersection_over_union(self.TEMP_BBOX, [startX, startY, endX, endY])
                if iou > 0.5:
                    self.temperature = "{0:.1f}".format(val)
                
            # show the output frame
            # draw temperature reading box
            lepton_frame = cv2.rectangle(lepton_frame, (self.CROP_X, self.CROP_Y), (self.CROP_X + self.SIZE, self.CROP_Y + self.SIZE),
                (255,255,255), 2)
            lepton_frame = cv2.resize(lepton_frame, (800, 600), interpolation=cv2.INTER_LINEAR)
            
            self.thermal_frame = lepton_frame

    def stop(self):
        self.face_detector.stop()
        while not self.face_detector.is_stopped:
            time.sleep(0.1)
        libuvc.uvc_stop_streaming(self.devh)
        _THREADING["shouldrun"] = False
        with q.mutex:
            q.queue.clear()
        self.thermal_frame = None
        self.temperature = None
        print("thermal stream stopped")
