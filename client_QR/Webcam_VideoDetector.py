#Import the neccesary libraries
import time
import threading
import cv2
import imutils
import dlib
from centroidtracker import CentroidTracker

_WEBCAM_PARAMS = {"webcam_source":"", "skip_frame":1,
                  "ready":False, "shouldrun":False,
                  "detect_result":[]}
_THREADING = {"stopEvent":threading.Event(), "thread":threading.Thread(target="")}

#Const from calibrate result
ZOOM_WIDTH = 660  #webcam adjust width. using actual frame size in VLC then compare it
CROP_Y = 82 #upper to start crop
CROP_X = 124 #left to start crop

class FaceDetect:

    def __init__(self, source="", skip=1):
        _WEBCAM_PARAMS["webcam_source"] = source
        _WEBCAM_PARAMS["skip_frame"] = skip
        self.objects = []
        self.obj_rects = []
        self.is_stopped = True

    def start(self):
        _THREADING["stopEvent"] = threading.Event()
        _THREADING["thread"] = threading.Thread(target=self.do_detections)
        _THREADING["thread"].start()

    def stop(self):
        _WEBCAM_PARAMS["shouldrun"] = False
        while not self.is_stopped:
            time.sleep(0.1)
        try:
            print("joining face detection thread. is_stopped=",self.is_stopped)
            _THREADING["thread"].join(timeout=1)
            if _THREADING["thread"].isAlive():
                # we timed out
                print("face detection thread refuse to die. TIMEOUT")
                _THREADING["stopEvent"].set()
            else:
                # we didn't
                print("face detection thread died.")
        except:
            pass

    def detect_result(self):
        return _WEBCAM_PARAMS["detect_result"]

    def isstarted(self):
        return _WEBCAM_PARAMS["shouldrun"]

    def do_detections(self):
        # face detector
        detector = dlib.get_frontal_face_detector()

        # instantiate our centroid tracker, then initialize a list to store
        # each of our dlib correlation trackers, followed by a dictionary to
        # map each unique object ID to a TrackableObject
        ct = CentroidTracker(maxDisappeared=40, maxDistance=50)
        trackers = []
        

        total_frames = 0
        cap = cv2.VideoCapture(_WEBCAM_PARAMS["webcam_source"])

        # Check if camera opened successfully
        if not cap.isOpened():
            print("Error opening video stream or file")
            return
        print ("~~~ START TO DETECT ~~~")
        _WEBCAM_PARAMS["shouldrun"] = True
        self.is_stopped = False
        while(_WEBCAM_PARAMS["shouldrun"]):
            # Capture frame-by-frame
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            frame = cv2.flip(frame, 1)
            frame = imutils.resize(frame, width=ZOOM_WIDTH)
            background = frame[CROP_Y:CROP_Y+300, CROP_X:CROP_X+400]
            rgb = cv2.cvtColor(background, cv2.COLOR_BGR2RGB)
            total_frames += 1

            rects = []
            # check to see if we should run a more computationally expensive
            # object detection method to aid our tracker
            if total_frames % _WEBCAM_PARAMS["skip_frame"] == 0:
                total_frames = 0
                # initialize our new set of object trackers
                trackers = []

                # convert the frame to a blob and pass the blob through the
                # network and obtain the detections
                detections = detector(cv2.cvtColor(background, cv2.COLOR_BGR2GRAY), 0)

                # loop over the detections
                for k, d in enumerate(detections):
                    # compute the (x, y)-coordinates of the bounding box
                    # for the object
                    (startX, startY, endX, endY) = (d.left(), d.top(), d.right(), d.bottom())

                    # construct a dlib rectangle object from the bounding
                    # box coordinates and then start the dlib correlation
                    # tracker
                    tracker = dlib.correlation_tracker()
                    rect = dlib.rectangle(startX, startY, endX, endY)
                    tracker.start_track(rgb, rect)

                    # add the tracker to our list of trackers so we can
                    # utilize it during skip frames
                    trackers.append(tracker)

            # otherwise, we should utilize our object *trackers* rather than
            # object *detectors* to obtain a higher frame processing throughput
            else:
                # loop over the trackers
                for tracker in trackers:
                    # update the tracker and grab the updated position
                    tracker.update(rgb)
                    pos = tracker.get_position()

                    # unpack the position object
                    startX = int(pos.left())
                    startY = int(pos.top())
                    endX = int(pos.right())
                    endY = int(pos.bottom())

                    # add the bounding box coordinates to the rectangles list
                    rects.append((startX, startY, endX, endY))

            self.objects, self.obj_rects = ct.update(rects)
        cap.release()
        print("Face Detector stopped")
        self.is_stopped = True
