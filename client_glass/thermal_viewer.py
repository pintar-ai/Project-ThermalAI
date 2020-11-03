# import the necessary packages
from trackableobject import TrackableObject
from imutils.video import FPS
import numpy as np
import time
import cv2
from Webcam_VideoDetector import FaceDetect
from uvctypes import *
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
import platform

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

face_detector = FaceDetect(source=0, skip=3)
face_detector.start()
trackableObjects = {}

window_name = "Thermal Viewer"
cv2.namedWindow(window_name, cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

#Lepton Variable
ctx = POINTER(uvc_context)()
dev = POINTER(uvc_device)()
devh = POINTER(uvc_device_handle)()
ctrl = uvc_stream_ctrl()

res = libuvc.uvc_init(byref(ctx), 0)
if res < 0:
    print("uvc_init error")
    exit(1)

res = libuvc.uvc_find_device(ctx, byref(dev), PT_USB_VID, PT_USB_PID, 0)
if res < 0:
    print("uvc_find_device error")
    exit(1)

res = libuvc.uvc_open(dev, byref(devh))
if res < 0:
    print("uvc_open error")
    exit(1)

print("device opened!")

print_device_info(devh)
print_device_formats(devh)

frame_formats = uvc_get_frame_formats_by_guid(devh, VS_FMT_GUID_Y16)
if len(frame_formats) == 0:
    print("device does not support Y16")
    exit(1)

libuvc.uvc_get_stream_ctrl_format_size(devh, byref(ctrl), UVC_FRAME_FORMAT_Y16,
    frame_formats[0].wWidth, frame_formats[0].wHeight, int(1e7 / frame_formats[0].dwDefaultFrameInterval)
)

res = libuvc.uvc_start_streaming(devh, byref(ctrl), PTR_PY_FRAME_CALLBACK, None, 0)
if res < 0:
    print("uvc_start_streaming failed: {0}".format(res))
    exit(1)

# initialize the total number of frames processed thus far, along
# with the total number of objects that have moved either up or down
totalFrames = 0
tempThreshold = 35
totalHigh = 0

# start the frames per second throughput estimator
fps = FPS().start()

# loop over frames from the video stream
while True:
    detector_ready = face_detector.isstarted()
    # grab frame from each camera
    data = q.get(True, 500)
    if data is None or not detector_ready:
        time.sleep(1.0)
        continue
    data = cv2.resize(data[:,:], (400, 300))
    raw_data = data.copy()
    lepton_frame = raw_to_8bit(data)
    
    # use the centroid tracker to associate the (1) old object
    # centroids with (2) the newly computed object centroids
    objects = face_detector.objects
    obj_rects = face_detector.obj_rects

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
        if 35 < val < 37:
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

            # check to see if the object has been counted or not
            if not to.counted:
                if val > tempThreshold:
                    totalHigh += 1
                    to.counted = True

        # store the trackable object in our dictionary
        trackableObjects[objectID] = to

        # draw both the ID of the object and the centroid of the
        # object on the output frame
        text = "ID {}".format(objectID)
        cv2.putText(lepton_frame, text, (centroid[0] - 10, centroid[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        cv2.circle(lepton_frame, (centroid[0], centroid[1]), 4, color, -1)
        cv2.rectangle(lepton_frame, (startX, startY), (endX, endY),
            color, 2)
        cv2.putText(lepton_frame, temp, (startX, startY - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2)

    # construct a tuple of information we will be displaying on the
    # frame
    info = [
        ("Date ", time.strftime("%d-%m-%Y")),
        ("Time ", time.strftime("%H:%M:%S")),
        ("Person in sight ", len(obj_rects)),
        ("Total person ", len(trackableObjects))
    ]

    # loop over the info tuples and draw them on our frame
    lepton_frame = cv2.copyMakeBorder(lepton_frame,0,0,0,250,cv2.BORDER_CONSTANT,value=[0, 0, 0])
    for (i, (k, v)) in enumerate(info):
        text = "{}: {}".format(k, v)
        cv2.putText(lepton_frame, text, (400,20+(20*i)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    # show the output frame
    lepton_frame = cv2.resize(lepton_frame, (1280,590), interpolation=cv2.INTER_LINEAR)
    cv2.imshow(window_name, lepton_frame)
    key = cv2.waitKey(1) & 0xFF

    # if the `q` key was pressed, break from the loop
    if key == ord("q"):
        break

    # increment the total number of frames processed thus far and
    # then update the FPS counter
    totalFrames += 1
    fps.update()

# stop the timer and display FPS information
fps.stop()
print("[INFO] elapsed time: {:.2f}".format(fps.elapsed()))
print("[INFO] approx. FPS: {:.2f}".format(fps.fps()))

face_detector.stop()

# close any open windows
cv2.destroyAllWindows()
